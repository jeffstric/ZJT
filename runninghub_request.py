import requests
import yaml
import time
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from config_util import get_config_path

class TaskStatus(Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"


@dataclass
class NodeInfo:
    node_id: str
    node_name: str
    field_name: str
    field_type: str
    field_value: str
    description: str


@dataclass
class TaskResult:
    file_url: str
    file_type: str
    task_cost_time: str
    node_id: str


class RunningHubClient:
    # nanobanana 图片编辑的固定配置
    WEBAPP_ID = "1960639129312780290"
    QUICK_CREATE_CODE = "005"
    
    def __init__(self, config_path: str = "config.yml", api_key: str = None):
        """
        Initialize RunningHub API client
        
        Args:
            config_path: Path to YAML configuration file
            api_key: Optional API key to override the one in config file
        """
        self.config = self._load_config(config_path)
        self.host = self.config["runninghub"]["host"]
        self.api_key = api_key if api_key is not None else self.config["runninghub"]["api_key"]
        self.request_timeout = self.config["timeout"]["request_timeout"]
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    
    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make HTTP POST request to RunningHub API
        
        Args:
            endpoint: API endpoint path
            data: Request payload
            
        Returns:
            API response as dictionary
            
        Raises:
            requests.RequestException: If request fails
            ValueError: If response format is invalid
        """
        url = f"{self.host}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            response = requests.post(
                url, 
                json=data, 
                headers=headers, 
                timeout=self.request_timeout
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Check if API returned error
            if result.get("code") != 0:
                raise ValueError(f"API Error: {result.get('msg', 'Unknown error')}")
                
            return result
            
        except requests.RequestException as e:
            raise requests.RequestException(f"Request failed: {str(e)}")
        except ValueError as e:
            if "API Error" in str(e):
                raise
            raise ValueError(f"Invalid response format: {str(e)}")
    
    def run_task(self, node_info_list: List[NodeInfo],transaction_id:str) -> Dict[str, Any]:
        """
        Submit a new task to RunningHub
        
        Args:
            node_info_list: List of node information for the workflow
            
        Returns:
            Task submission response containing taskId, clientId, etc.
        """
        endpoint = "/task/openapi/quick-ai-app/run"
        
        # Convert NodeInfo objects to dictionaries
        nodes_data = []
        for node in node_info_list:
            nodes_data.append({
                "nodeId": node.node_id,
                "nodeName": node.node_name,
                "fieldName": node.field_name,
                "fieldType": node.field_type,
                "fieldValue": node.field_value,
                "description": node.description
            })
        
        payload = {
            "webappId": self.WEBAPP_ID,
            "apiKey": self.api_key,
            "quickCreateCode": self.QUICK_CREATE_CODE,
            "nodeInfoList": nodes_data,
            "transactionId": transaction_id
        }
        
        return self._make_request(endpoint, payload)
    
    def check_status(self, task_id: str) -> TaskStatus:
        """
        Check the status of a submitted task
        
        Args:
            task_id: Task ID returned from run_task
            
        Returns:
            Current task status
        """
        endpoint = "/task/openapi/status"
        
        payload = {
            "apiKey": self.api_key,
            "taskId": task_id
        }
        
        response = self._make_request(endpoint, payload)
        status_str = response.get("data", "")
        
        try:
            return TaskStatus(status_str)
        except ValueError:
            raise ValueError(f"Unknown task status: {status_str}")
    
    def get_outputs(self, task_id: str) -> List[TaskResult]:
        """
        Get the output results of a completed task
        
        Args:
            task_id: Task ID returned from run_task
            
        Returns:
            List of task results with file URLs and metadata
        """
        endpoint = "/task/openapi/outputs"
        
        payload = {
            "apiKey": self.api_key,
            "taskId": task_id
        }
        
        response = self._make_request(endpoint, payload)
        results_data = response.get("data", [])
        
        results = []
        for item in results_data:
            result = TaskResult(
                file_url=item.get("fileUrl", ""),
                file_type=item.get("fileType", ""),
                task_cost_time=item.get("taskCostTime", ""),
                node_id=item.get("nodeId", "")
            )
            results.append(result)
        
        return results
    
    def wait_for_completion(self, task_id: str, 
                          timeout: Optional[int] = None, 
                          check_interval: Optional[int] = None) -> TaskStatus:
        """
        Wait for a task to complete by polling its status
        
        Args:
            task_id: Task ID to monitor
            timeout: Maximum time to wait in seconds (default from config)
            check_interval: Time between status checks in seconds (default from config)
            
        Returns:
            Final task status
            
        Raises:
            TimeoutError: If task doesn't complete within timeout
        """
        if timeout is None:
            timeout = self.config["timeout"]["status_check_timeout"]
        if check_interval is None:
            check_interval = self.config["timeout"]["status_check_interval"]
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.check_status(task_id)
            
            if status in [TaskStatus.SUCCESS, TaskStatus.FAILED]:
                return status
            
            time.sleep(check_interval)
        
        raise TimeoutError(f"Task {task_id} did not complete within {timeout} seconds")
    
    def run_and_wait(self, node_info_list: List[NodeInfo], 
                     timeout: Optional[int] = None) -> tuple[str, List[TaskResult]]:
        """
        Submit a task and wait for completion, then return results
        
        Args:
            node_info_list: List of node information for the workflow
            timeout: Maximum time to wait for completion
            
        Returns:
            Tuple of (task_id, results)
            
        Raises:
            RuntimeError: If task fails
            TimeoutError: If task doesn't complete within timeout
        """
        # Submit task
        response = self.run_task(node_info_list, None)
        task_id = response["data"]["taskId"]
        
        # Wait for completion
        final_status = self.wait_for_completion(task_id, timeout)
        
        if final_status == TaskStatus.FAILED:
            raise RuntimeError(f"Task {task_id} failed")
        
        # Get results
        results = self.get_outputs(task_id)
        
        return task_id, results


# Convenience functions for common use cases
def create_image_edit_nodes(image_url: str, prompt: str) -> List[NodeInfo]:
    """
    Create node info list for image editing workflow
    
    Args:
        image_url: URL of the input image
        prompt: Text prompt for editing
        
    Returns:
        List of NodeInfo objects for the workflow
    """
    return [
        NodeInfo(
            node_id="2",
            node_name="LoadImage",
            field_name="image",
            field_type="IMAGE",
            field_value=image_url,
            description="上传图像"
        ),
        NodeInfo(
            node_id="16",
            node_name="RH_Translator",
            field_name="prompt",
            field_type="STRING",
            field_value=prompt,
            description="输入文本"
        )
    ]




def run_image_edit_task(image_url: str, prompt: str, timeout: int = 180) -> tuple[str, List[TaskResult]]:
    """
    Run image editing task with URL input and wait for completion
    
    Args:
        image_url: URL of the input image
        prompt: Text prompt for editing
        timeout: Maximum time to wait for completion in seconds (default: 180s = 3 minutes)
        
    Returns:
        Tuple of (task_id, results)
        
    Raises:
        RuntimeError: If task fails
        TimeoutError: If task doesn't complete within timeout
    """
    # Initialize client
    client = RunningHubClient()
    
    # Create nodes for image editing
    nodes = create_image_edit_nodes(image_url, prompt)
    
    # Submit and wait for completion
    task_id, results = client.run_and_wait(nodes, timeout)
    
    return task_id, results


def run_ai_app_task(
    webapp_id: str,
    api_key: str,
    node_info_list: List[Dict[str, str]],
    config_path: str = None
) -> Dict[str, Any]:
    """
    Run AI app task using the ai-app/run endpoint
    
    Args:
        webapp_id: The webapp ID for the AI app
        api_key: API key for authentication
        node_info_list: List of node information dictionaries with nodeId, fieldName, fieldValue, etc.
        config_path: Path to configuration file (default: auto-detect based on comfyui_env)
        
    Returns:
        API response as dictionary
        
    Raises:
        requests.RequestException: If request fails
        ValueError: If response format is invalid
    """
    # Auto-detect config file based on environment if not specified
    config_path = get_config_path(config_path)
    
    # Load config to get host
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)
    
    host = config["runninghub"]["host"]
    endpoint = "/task/openapi/ai-app/run"
    url = f"{host}{endpoint}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "webappId": webapp_id,
        "apiKey": api_key,
        "nodeInfoList": node_info_list
    }
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=config["timeout"]["request_timeout"]
        )
        response.raise_for_status()
        
        result = response.json()
        
        # Return result directly, let caller handle code != 0
        return result
        
    except requests.RequestException as e:
        raise requests.RequestException(f"Request failed: {str(e)}")
    except ValueError as e:
        raise ValueError(f"Invalid response format: {str(e)}")



def run_ai_app_task_sync(
    webapp_id: str,
    api_key: str,
    node_info_list: List[Dict[str, str]],
    timeout: int = 180,
    config_path: str = None,
    transaction_id: str = None
) -> tuple[str, List[TaskResult]]:
    """
    Run AI app task and wait for completion (synchronous)
    
    Args:
        webapp_id: The webapp ID for the AI app
        api_key: API key for authentication
        node_info_list: List of node information dictionaries
        timeout: Maximum time to wait for completion in seconds (default: 180s = 3 minutes)
        config_path: Path to configuration file (default: auto-detect based on comfyui_env)
        
    Returns:
        Tuple of (task_id, results)
        
    Raises:
        RuntimeError: If task fails
        TimeoutError: If task doesn't complete within timeout
    """
    # Auto-detect config file based on environment if not specified
    if config_path is None:
        env = os.getenv("comfyui_env", "prod")
        config_path = "config_dev.yml" if env == "dev" else "config.yml"
    
    # Create client instance with custom api_key
    client = RunningHubClient(config_path=config_path, api_key=api_key)
    check_interval = client.config["timeout"].get("status_check_interval", 5)
    
    # Submit task
    result = run_ai_app_task(webapp_id, api_key, node_info_list, config_path, transaction_id)
    
    # Check if task submission failed
    if result.get("code") != 0:
        error_msg = result.get("msg", "Unknown error")
        raise RuntimeError(f"Task submission failed: {error_msg}")
    
    task_id = result.get("data", {}).get("taskId")
    if not task_id:
        raise RuntimeError("Failed to get task ID from response")
    
    # Wait for completion
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Task {task_id} did not complete within {timeout} seconds")
        
        # Use client's check_status method
        status = client.check_status(task_id)
        
        if status == TaskStatus.SUCCESS:
            # Use client's get_outputs method
            results = client.get_outputs(task_id)
            return task_id, results
        elif status == TaskStatus.FAILED:
            raise RuntimeError(f"Task {task_id} failed")
        
        # Still running or queued, wait before checking again
        time.sleep(check_interval)

# Example usage
if __name__ == "__main__":
    # Initialize client
    client = RunningHubClient()

    # Example: Create nodes for image editing
    nodes = create_image_edit_nodes(
        image_url="https://www.perseids.cn/007mfYxXly1hvdnrv6k9ij30qo140425.jpg",
        prompt="将人物制作成为手办"
    )

    try:
        # Submit and wait for completion
        task_id, results = client.run_and_wait(nodes)
        
        print(f"Task completed: {task_id}")
        for result in results:
            print(f"Output: {result.file_url} ({result.file_type})")
            print(f"Cost time: {result.task_cost_time}s")
            
    except Exception as e:
        print(f"Error: {e}")
