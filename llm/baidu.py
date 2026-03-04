import json
import httpx
from config.config_util import get_config_value

API_KEY = get_config_value('llm', 'baidu', 'api_key', default='')
QIANFAN_API_URL = get_config_value('llm', 'baidu', 'api_url', default='https://qianfan.baidubce.com/v2/chat/completions')
DEFAULT_MODEL = get_config_value('llm', 'baidu', 'model', default='ernie-4.5-turbo-vl-latest')

# 基础默认提示词（不含动态参数部分）
BASE_DEFAULT_PROMPT = """请根据上传的图片生成一个短视频的脚本内容。要求如下： 1. 脚本应包括多个常见且吸引人的场景，前几帧不允许出现我给的参考图片的静态帧，还需要内容特别引人注目，画面内容要真实且富有风格。   2. 避免拟人化内容，但可以在部分场景中加入模特以增强视觉效果。 3. 确保脚本内容不侵犯任何版权。4. 整个视频时长不得超过15秒。 5. 包含专业的镜头要求和拍摄技巧。 6. 所有细节描述需具体且到位，以确保画面呈现的清晰。 7. 视频风格是用户分享，不要营销卖货。 8. 视频完整，头尾呼应 9. 但是除了展示的商品外，画面中不得出现任何文字内容。 10. 视频应包含多样化的场景，避免单一场景。 11. 生成ai脚本，脚本形式为Json格式，将每个场景中的Json字段的内容都接在Text字段中，不要省略字段，也不要概括内容，参照{
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

async def call_ernie_vl_api(image_url1, image_url2=None, image_url3=None, image_url4=None, image_url5=None, prompt="", add_detail="否", need_narration="否", extra_prompt=""):
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
            final_prompt += "  整个脚本中 必须要有特写镜头和微距镜头，特写镜头的SceneDescription、VisualRequirements、ActionDesign字段需包含详细描写（如产品材质纹理、光线角度、模特动作细节、场景环境细节等），增强视频画面的可执行性"
        else:
            final_prompt += "  整个脚本中 不需要任何特写镜头和微距镜头"
        
        # 若需要旁白，追加提示
        if need_narration.strip().lower() in ["是", "yes", "y"]:
            final_prompt += "，且每张脚本的Narration字段需包含具体、有感染力的带货旁白（突出产品卖点、场景氛围或用户利益点），旁白时长与视频总时长匹配，语言简洁有记忆点"
        else:
            final_prompt += "，且每张脚本的Narration字段需为空"

        final_prompt+="1. 注意实物的尺寸比例，不要出现商品过大或者过小的问题（比如商品如果是服装，袖子不能太长，需要露出手）。2. 视频中的商品请和图片中的商品保持一致，特别是商品上的图案、图案位置都必须保持一模一样。3. 画面中除了商品外，其他部分禁止有文字 或者字幕。4. 需要有旁白声音。5. 禁止出现画面中不真实的部分，比如多条腿、穿模、物体漂浮等违反物理规律的画面"

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
            "model": DEFAULT_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ],
            "temperature": 0.6,
            "top_p": 0.8,
            "penalty_score": 1,
            "stop": []
        }, ensure_ascii=False)

        # 调用百度千帆API
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {API_KEY}'
        }
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                QIANFAN_API_URL,
                headers=headers,
                data=payload.encode("utf-8")
            )

        if response.status_code != 200:
            error_detail = {
                "status_code": response.status_code,
                "response_text": response.text,
                "error": f"百度千帆API调用失败: HTTP {response.status_code}"
            }
            return error_detail

        response_data = response.json()
        return response_data
    except Exception as e:
        return {"error": f"百度千帆API异常: {str(e)}"}