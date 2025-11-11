import requests
import json

# 百度千帆API Key（已保留你的密钥）
API_KEY = "bce-v3/ALTAK-RW7WrM9SbRGJBisQ6n41v/223a3bda9f1652f86d74d5d8b937201fc3c86dde"
# 百度千帆API地址
QIANFAN_API_URL = "https://qianfan.baidubce.com/v2/chat/completions"

# 基础默认提示词（不含动态参数部分）
BASE_DEFAULT_PROMPT = """参考用户上传的图片，生成ai脚本，脚本形式为Json格式，将每个场景中的Json字段的内容都接在Text字段中，不要省略字段，也不要概括内容，参照{
  "VideoTitle": "《扇影流年》",
  "VideoStyle": "用户生活分享 · 自然美学 · 动态场景融合",
  "TotalDuration": "5秒",
  "ScriptScenes": [
    {
      "SceneNumber": "镜头1",
      "TimeRange": "0-2秒",
      "SceneName": "风起晨光",
      "SceneDescription": "清晨竹林，微风拂过竹叶，一道粉色光影（扇面虚化投影）在地面轻摇，与竹影交错成动态条纹。",
      "CameraTechniques": "低角度平移镜头，慢门拍摄强化光影流动感",
      "SoundEffects": "自然风声",
      "VisualRequirements": "无人物，仅保留扇面色彩与光影的抽象互动，避免静态展示",
      "ActionDesign": "无动作设计，仅展示扇面与光影的互动",
      "Costume": "无"
      "Text":"镜头 1（0-2 秒）《风起晨光》：清晨竹林，微风拂过竹叶，一道粉色光影（扇面虚化投影）在地面轻摇，与竹影交错成动态条纹。低角度平移镜头，慢门拍摄强化光影流动感。自然风声，无人物，仅保留扇面色彩与光影的抽象互动，避免静态展示。"
    },
    {"SceneNumber": "镜头 2","TimeRange": "2-5 秒",
     "SceneName": "茶室闲韵"
     "SceneDescription": "传统茶室，模特（素色棉麻长裙）侧坐于榻榻米，手持闭合扇子轻倚窗边，扇骨与竹帘光影重叠。",
     "CameraTechniques": "侧逆光中景跟拍，浅景深虚化背景陶器与绿植",
     "VisualRequirements": "突出扇子作为 ' 环境元素 ' 的柔和存在",
     "ActionDesign": "模特指尖轻触扇骨，扇面微启又合，动作自然无刻意感",
     "Costume": "素色棉麻长裙",
     "Text": "镜头 2（2-5 秒）《茶室闲韵》：传统茶室，模特（素色棉麻长裙）侧坐于榻榻米，手持闭合扇子轻倚窗边，扇骨与竹帘光影重叠。侧逆光中景跟拍，浅景深虚化背景陶器与绿植，突出扇子作为 ' 环境元素 ' 的柔和存在，模特动作设计为指尖轻触扇骨、扇面微启又合，整体动作自然无刻意感。"
     }
  ]
}，需要生成1份JSON脚本，脚本结构完整，符合上述JSON格式要求，要求生成的脚本时长只能为15秒，就算后面有其他要求，也只能是15秒"""

def call_ernie_vl_api(image_url1, image_url2=None, image_url3=None, image_url4=None, image_url5=None, prompt="", add_detail="否", need_narration="否", extra_prompt=""):
    """
    调用百度千帆ERNIE-VL API生成视频脚本
    
    Args:
        image_url1: 第一张图片URL（必传）
        image_url2: 第二张图片URL（可选）
        image_url3: 第三张图片URL（可选）
        image_url4: 第四张图片URL（可选）
        image_url5: 第五张图片URL（可选）
        prompt: 自定义提示词（可选）
        add_detail: 是否添加细节描写（默认"否"）
        need_narration: 是否需要旁白（默认"否"）
        extra_prompt: 额外提示词（可选）
    
    Returns:
        API响应的JSON数据
    """
    try:
        # 动态构建最终提示词
        final_prompt = prompt if prompt else BASE_DEFAULT_PROMPT
        
        # 若有额外提示词，追加到基础提示词后方
        if extra_prompt:
            final_prompt += f"，{extra_prompt}"
        
        # 若需要细节描写，追加提示
        if add_detail.strip().lower() in ["是", "yes", "y"]:
            final_prompt += "，且每张脚本的SceneDescription、VisualRequirements、ActionDesign字段需包含详细描写（如产品材质纹理、光线角度、模特动作细节、场景环境细节等），增强视频画面的可执行性"
        
        # 若需要旁白，追加提示
        if need_narration.strip().lower() in ["是", "yes", "y"]:
            final_prompt += "，且每张脚本的Narration字段需包含具体、有感染力的带货旁白（突出产品卖点、场景氛围或用户利益点），旁白时长与视频总时长匹配，语言简洁有记忆点"

        # 构造content数组
        content = []
        content.append({"type": "image_url", "image_url": {"url": image_url1}})
        if image_url2:
            content.append({"type": "image_url", "image_url": {"url": image_url2}})
        if image_url3:
            content.append({"type": "image_url", "image_url": {"url": image_url3}})
        if image_url4:
            content.append({"type": "image_url", "image_url": {"url": image_url4}})
        if image_url5:
            content.append({"type": "image_url", "image_url": {"url": image_url5}})
        content.append({"type": "text", "text": final_prompt})

        # 构造百度千帆API请求参数
        payload = json.dumps({
            "model": "ernie-4.5-turbo-vl-latest",
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ],
            "temperature": 0.6,
            "top_p": 0.8
        }, ensure_ascii=False)

        # 调用百度千帆API
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {API_KEY}'
        }
        response = requests.post(
            QIANFAN_API_URL,
            headers=headers,
            data=payload.encode("utf-8")
        )
        response_data = response.json()
        
        return response_data

    except Exception as e:
        return {"error": str(e)}