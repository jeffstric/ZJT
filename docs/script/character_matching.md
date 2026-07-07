# 剧本解析角色匹配功能

## 更新日期
- 2026年6月9日：新增角色数据库匹配功能
- 2026年6月9日：修复前端未使用 db_character_info 的问题
- 2026年6月9日：修复角色名称不一致问题（LLM名称 vs 数据库名称）
- 2026年6月9日：优化分镜节点角色显示，将标签改为提示词区域的图片形式
- 2026年6月9日：新增在线缩略图服务，优化角色头像加载性能

## 问题背景

在剧本解析过程中，LLM 会根据剧本文字自行生成角色名称（如"布冯"、"C罗"、"梅西"），但数据库中的角色名称可能是不同格式（如"阿方索戴维斯_AlphonsoDavies"）。这导致解析出的角色无法与数据库中的角色正确关联。

**根本原因**：`script_parser.py` 中加载了数据库场景和道具列表传给 LLM 做匹配，但没有加载数据库角色列表。

## 解决方案

### 1. 加载数据库角色列表

在 `llm/script_parser.py` 中，新增加载数据库角色的逻辑：

```python
# 获取数据库中的角色列表（如果提供了world_id）
db_characters_text = ""
if world_id is not None:
    from model.character import CharacterModel
    characters_result = CharacterModel.list_by_world(world_id=world_id, page=1, page_size=50)
    db_characters = characters_result.get('data', []) if characters_result else []
    
    if db_characters:
        char_lines = []
        for char in db_characters:
            char_desc = char.get('identity', '') or char.get('appearance', '') or char.get('personality', '无')
            char_lines.append(f"- ID: {char['id']}, 名称: {char['name']}, 描述: {char_desc}")
        
        db_characters_text = f"""
**【数据库已有角色列表】**
以下是数据库中已存在的角色（最多50个），如果剧本中的角色与数据库中的角色相同或相似，请在返回的character对象中设置character_db_id字段为对应的数据库角色ID：
...
"""
```

### 2. 更新 LLM Prompt

在系统提示词中添加角色匹配规则：

```
8. **角色与数据库关联**：每个character必须包含character_db_id字段
   - 如果剧本中的角色与数据库中已有角色匹配，则将character_db_id设置为数据库角色的ID
   - 如果是新角色，不在数据库中，则character_db_id必须设置为null
   - 匹配时考虑角色名称和描述的相似性，不需要完全一致
   - **【警告】严禁编造不存在的character_db_id**
```

在用户提示词中添加数据库角色列表：

```
数据库中的角色列表：
```{db_characters_text} ```
```

更新 JSON 格式示例，添加 `character_db_id` 字段：

```json
"characters": [
    {
      "id": "char_001",
      "name": "人物名称",
      "character_db_id": 123,
      "role": "主角/配角/群演",
      "description": "外貌和特征描述",
      "gender": "男/女",
      "age_range": "年龄范围"
    }
]
```

### 3. 服务端后处理

在 `server.py` 中添加角色匹配后处理函数：

```python
def _match_character_to_db(character_id: str, characters: list) -> tuple:
    """
    匹配角色到数据库
    
    Returns:
        (db_character_id, reference_image, character_name) 元组
    """
    char_map = {c['id']: c for c in characters}
    current_char = char_map.get(character_id)
    
    if not current_char:
        return (None, None, None)
    
    db_id = current_char.get('character_db_id')
    if db_id is not None:
        from model.character import CharacterModel
        db_character = CharacterModel.get_by_id(db_id)
        if db_character:
            return (db_id, db_character.reference_image, db_character.name)
    
    return (None, None, None)
```

在 `parse_script` 接口中添加后处理：

```python
# 为每个shot中的characters_present添加db_character信息
characters = parsed_data.get('characters', [])
for group in shot_groups:
    shots = group.get('shots', [])
    for shot in shots:
        characters_present = shot.get('characters_present', [])
        db_character_info = []
        for char_id in characters_present:
            db_char_id, db_char_pic, db_char_name = _match_character_to_db(char_id, characters)
            db_character_info.append({
                'character_id': char_id,
                'db_character_id': db_char_id,
                'db_character_pic': db_char_pic,
                'db_character_name': db_char_name
            })
        shot['db_character_info'] = db_character_info
```

## 数据流

```
剧本内容
    ↓
script_parser.py
    ↓
加载数据库角色列表 (CharacterModel.list_by_world)
    ↓
格式化为文本传给 LLM
    ↓
LLM 解析剧本，生成 characters 数组（包含 character_db_id）
    ↓
server.py 后处理
    ↓
匹配 character_db_id 到数据库角色
    ↓
返回 db_character_info（包含 db_character_id, db_character_pic, db_character_name）
```

## 返回数据示例

```json
{
  "code": 0,
  "message": "解析成功",
  "data": {
    "characters": [
      {
        "id": "char_001",
        "name": "布冯",
        "character_db_id": 4651,
        "role": "主角",
        "description": "...",
        "gender": "男",
        "age_range": "45-50"
      }
    ],
    "shot_groups": [
      {
        "group_id": "grp_001",
        "group_name": "米兰公寓开场",
        "shots": [
          {
            "shot_id": "s001",
            "characters_present": ["char_001"],
            "db_character_info": [
              {
                "character_id": "char_001",
                "db_character_id": 4651,
                "db_character_pic": "http://...",
                "db_character_name": "阿方索戴维斯_AlphonsoDavies"
              }
            ]
          }
        ]
      }
    ]
  }
}
```

## 与场景/道具匹配的对比

| 数据类型 | DB加载 | LLM匹配字段 | 后处理函数 | 返回字段 |
|---------|--------|------------|-----------|---------|
| 场景(Location) | ✅ `LocationModel.get_tree_by_world` | `location_db_id` | `_match_location_to_db` | `db_location_id`, `db_location_pic`, `location_name` |
| 道具(Props) | ✅ `PropsModel.list_by_world` | `props_db_id` | 无 | 无 |
| **角色(Character)** | ✅ `CharacterModel.list_by_world` | `character_db_id` | `_match_character_to_db` | `db_character_info` |

## 前端实现

### 问题描述

原来的前端实现存在以下问题：
1. 完全忽略后端返回的 `db_character_info`
2. 只从提示词文本中提取 `【【角色名】】` 模式
3. 通过精确名称匹配 `state.worldCharacters`，如果名称不匹配则无法关联

### 解决方案

在 `web/js/nodes.js` 中修改了角色匹配逻辑：

**1. 新增 `getCharactersFromDbInfo()` 函数**

优先使用后端返回的 `db_character_info` 匹配角色：

```javascript
function getCharactersFromDbInfo() {
  const shotJson = node.data.shotJson || {};
  const dbCharInfo = shotJson.db_character_info;
  if(!dbCharInfo || !Array.isArray(dbCharInfo) || dbCharInfo.length === 0) {
    return null;
  }

  const worldChars = state.worldCharacters || [];
  const matchedNames = [];

  dbCharInfo.forEach(info => {
    if(info.db_character_id && info.db_character_name) {
      // 后端已匹配到数据库角色，使用 db_character_name
      if(!matchedNames.includes(info.db_character_name)) {
        matchedNames.push(info.db_character_name);
      }
    } else if(info.character_id) {
      // 后端未匹配到，尝试从 scriptData.characters 中查找名称
      const scriptData = node.data.shotJson?.scriptData || {};
      const characters = scriptData.characters || [];
      const charObj = characters.find(c => c.id === info.character_id);
      if(charObj && charObj.name) {
        const existsInWorld = worldChars.some(wc => wc.name === charObj.name);
        if(existsInWorld && !matchedNames.includes(charObj.name)) {
          matchedNames.push(charObj.name);
        }
      }
    }
  });

  return matchedNames.length > 0 ? matchedNames : null;
}
```

**2. 修改初始匹配逻辑**

```javascript
// 优先使用 db_character_info，否则从提示词提取
const dbMatchedChars = getCharactersFromDbInfo();
if(dbMatchedChars) {
  node.data.refCharacters = dbMatchedChars;
} else {
  const initMode = node.data.videoMode || 'first_last_frame';
  const initPromptSource = initMode === 'multi_reference'
    ? (node.data.videoPromptText || node.data.videoPrompt || '')
    : (node.data.imagePrompt || '');
  node.data.refCharacters = extractCharacterNames(initPromptSource);
}
```

**3. 修改 `updateShotReferences()` 函数**

确保刷新引用时也优先使用 `db_character_info`：

```javascript
function updateShotReferences() {
  // 重新匹配角色：优先使用 db_character_info，否则从提示词提取
  const dbMatchedChars = getCharactersFromDbInfo();
  if(dbMatchedChars) {
    node.data.refCharacters = dbMatchedChars;
  } else {
    const mode = node.data.videoMode || 'first_last_frame';
    const promptSource = mode === 'multi_reference'
      ? (node.data.videoPromptText || node.data.videoPrompt || '')
      : (node.data.imagePrompt || '');
    node.data.refCharacters = extractCharacterNames(promptSource);
  }
  renderSceneTags();
  renderPropTags();
  renderCharTags();
}
```

### 匹配流程

```
shotJson.db_character_info
    ↓
检查 db_character_id 和 db_character_name
    ↓
如果存在 → 直接使用 db_character_name
    ↓
如果不存在 → 从 scriptData.characters 查找名称
    ↓
匹配 state.worldCharacters（按名称）
    ↓
渲染角色标签
```

## 角色名称一致性修复

### 问题描述

LLM 生成的角色名称（如"布冯"）与数据库中的实际名称（如"阿方索戴维斯_AlphonsoDavies"）不一致，导致：
1. 前端无法通过名称匹配到 `state.worldCharacters`
2. 角色标签显示不正确

### 解决方案

#### 1. LLM Prompt 优化

在 `llm/script_parser.py` 的系统提示词中添加要求：

```
8. **角色与数据库关联**：每个character必须包含character_db_id字段
   - **【重要】当角色与数据库匹配时，name字段必须使用数据库中的角色名称**
   - 例如：如果数据库中角色名称是"阿方索戴维斯_AlphonsoDavies"，则 name 使用此名称
```

在用户提示词中添加要求：

```
6. **角色名称格式要求**：
   - **【极其重要】当角色与数据库匹配时（character_db_id不为null），【【角色名】】必须使用数据库中的角色名称**
   - 例如：使用"【【阿方索戴维斯_AlphonsoDavies】】"，而不是"【【布冯】】"
```

#### 2. 后端名称替换

在 `server.py` 的后处理中，将 LLM 生成的 `name` 替换为数据库名称：

```python
# 将LLM生成的角色名称替换为数据库中的实际名称
for char in characters:
    db_id = char.get('character_db_id')
    if db_id is not None:
        try:
            from model.character import CharacterModel
            db_character = CharacterModel.get_by_id(db_id)
            if db_character:
                # 保存LLM生成的名称作为备用
                char['llm_name'] = char.get('name')
                # 替换为数据库中的实际名称
                char['name'] = db_character.name
        except Exception as e:
            logger.warning(f"Failed to get character name for {db_id}: {e}")
```

### 修复后的数据流

```
剧本内容："布冯瘫在沙发里..."
    ↓
LLM 解析
    ↓
生成 characters: [{ id: "char_001", name: "布冯", character_db_id: 4649 }]
    ↓
后端处理
    ↓
查询数据库: CharacterModel.get_by_id(4649)
    ↓
替换名称: name = "阿方索戴维斯_AlphonsoDavies"
    ↓
保存备用: llm_name = "布冯"
    ↓
返回: [{ id: "char_001", name: "阿方索戴维斯_AlphonsoDavies", llm_name: "布冯", character_db_id: 4649 }]
```

## 角色完整出场约束（prompt 优化）

### 问题描述

多角色场景拆分后，画面提示词与视频提示词经常**遗漏角色**。典型表现：场景中有两个角色（如"奶酪"和"奶昔"），但
- 画面提示词（来自 `opening_frame_description + scene_detail`）两个角色全无；
- 视频提示词（来自 `description + scene_detail + action`）只剩其中一个（如只有奶酪，丢了奶昔）。

### 根因

全部位于 `llm/script_parser.py` 的 prompt 设计：

1. **prompt 自相矛盾**：系统提示词旧第 4 条"严禁描写外貌/服装/发型/身材"与旧第 11 条/用户提示词第 6 条"opening_frame_description 必须含服装"直接冲突，导致 LLM 为求"安全"而在画面提示词里**完全不提角色**。
2. **无"角色完整出场"硬性规则**：prompt 只要求"角色名用 `【【】】` 包裹"，从未要求镜头在场的每个角色都必须在画面/动作描写中出现，LLM 倾向于只挑显眼角色写。
3. **给 LLM 的角色信息片面**：注入数据库角色列表时 `char.get('identity') or char.get('appearance') or ...` 用 `or` 只取一个字段，LLM 对角色理解不全，更易漏写次要角色。

### 解决方案

#### 1. 区分"固有档案"与"当前镜头动态"（系统提示词第 4 条）

将"严禁描写外貌"细化为两类：
- **【严禁】固有档案**（避免与角色库冲突）：发型、肤色、体型、固定的标志性服装/饰品——这些由角色库统一提供；
- **【必须】当前镜头动态**：角色在画面中的位置、姿态、动作、表情、与其他角色/镜头的空间关系，并提及角色名称（`【【角色名】】`）。

同步去掉 `opening_frame_description` 要求中与第 4 条冲突的"服装"措辞（系统提示词第 11 条、用户提示词第 6 条、JSON 示例字段说明均改为"所有在场角色的位置、姿态、表情/动作"）。

#### 2. 角色完整出场硬性规则（系统提示词新增第 18 条、用户提示词新增 7.1 条）

- `characters_present` 列出的**每个角色**都必须在 `opening_frame_description`（画面提示词）中点名，并写出位置/姿态/表情/动作；
- `characters_present` 中的**每个角色**都至少在 `description` 或 `action`（视频提示词来源）中有可见动作或位置交代；
- 即使某角色没有台词或处于静态（如操控载具、观察、等待），也必须写出其位置与姿态，不能因为"不显眼"漏写。

正例（双角色场景）：
```
opening_frame_description: "【【奶酪】】趴在车窗边、手拍玻璃；【【奶昔】】坐在驾驶位、双手操控拉杆、神情严肃"
```
反例：
```
opening_frame_description 只写了【【奶酪】】，完全没提同场的【【奶昔】】 ✗
opening_frame_description 只写"【【奶酪】】和【【奶昔】】在车上"，没有各自的位置/姿态/动作 ✗
```

#### 3. 角色信息注入更完整（`script_parser.py:712` 附近）

把 `or` 单字段取值改为拼接 `身份 / 外貌 / 性格` 多维度信息（无值则跳过），让 LLM 对每个角色有更全面的认识：

```python
_parts = []
for _key, _label in (('identity', '身份'), ('appearance', '外貌'), ('personality', '性格')):
    _val = char.get(_key)
    if _val:
        _parts.append(f"{_label}: {_val}")
char_desc = "；".join(_parts) if _parts else "无"
```

### 与多人对话拆分（split_multi_dialogue）的衔接

"角色完整出场"规则与"多人对话拆分"规则本身逻辑自洽，但需注意措辞衔接，避免互相诱导：

- **逻辑自洽**：`split_multi_dialogue=True` 会把多人对话镜头拆成多个单人镜头，拆分后每个镜头 `characters_present` 只剩 1 个角色，此时"全员出场"=那 1 个角色出场即可。
- **措辞陷阱（已修正）**：早期版本的"角色完整出场"正例使用了"双角色同框"描述（如"奶酪+奶昔同框"），而拆分规则要求"严禁同时出现两个或多个角色"。两者并存时 LLM 可能为了凑同框而拒绝拆分，或只拆出部分角色。现已把"角色完整出场"正例改为**以 `characters_present` 为锚、模式无关**的抽象描述。
- **防漏拆要求**：在拆分规则末尾新增"防漏拆"约束——原镜头里有几个角色对话，就必须拆出几个对应的单人镜头；即使某角色台词很短（如"嗯""好的"），也要为其单独拆镜头，保证每个对话角色都有自己的画面出场。

### 范围说明

本次仅优化 `llm/script_parser.py` 的 prompt 与角色信息注入。组装层 `api/storyboard.py` 中 `character_desc` 只拼角色名、不带 `appearance` 的问题属独立次要项，不在本次范围内——本次通过让角色直接进入 `opening_frame_description/scene_detail/description/action` 文本本身来解决问题。

## 分镜节点角色显示优化

### UI 变化

**旧布局**：角色以文本标签形式显示在左侧"基础信息"区域的"场景/道具/角色"引用区

**新布局**：角色以 inline 图片形式嵌入提示词文本中，将【【角色名】】替换为角色头像标签

```
┌─────────────────────────────────────────┐
│ 2 提示词编辑                             │
│ ┌─────────────────────────────────────┐ │
│ │ 图片提示词                           │ │
│ │ ┌─────────────────────────────────┐ │ │
│ │ │ 中景：┌🧑┐深陷沙发，左手持爆米花 │ │ │
│ │ │ 桶，右手拿披萨...               │ │ │
│ │ └─────────────────────────────────┘ │ │
│ ├─────────────────────────────────────┤ │
│ │ 视频提示词                           │ │
│ │ ┌─────────────────────────────────┐ │ │
│ │ │ ┌🧑┐瘫在沙发上，电视光映在脸上  │ │ │
│ │ └─────────────────────────────────┘ │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘

其中 🧑 表示内联角色头像标签（圆形小头像 + 角色名）
```

### 实现细节

**1. 移除角色标签行**

从基础信息区域的角色行（`shot-ref-row`）被移除

**2. 替换 textarea 为 div**

将 readonly textarea 替换为 div 容器，用于渲染带内联角色标签的提示词：
```html
<div class="shot-prompt-display shot-frame-image-prompt-display"></div>
<div class="shot-prompt-display shot-frame-video-prompt-display"></div>
```

**3. 新增 renderPromptWithInlineChars() 函数**

将提示词文本中的【【角色名】】替换为内联角色头像标签：

```javascript
function renderPromptWithInlineChars(displayEl, promptText) {
  const pattern = /【【([^】]+)】】/g;
  let lastIndex = 0;
  let match;

  while((match = pattern.exec(promptText)) !== null) {
    // 添加匹配前的文本
    if(match.index > lastIndex) {
      displayEl.appendChild(document.createTextNode(promptText.substring(lastIndex, match.index)));
    }

    const charName = match[1].trim();
    const wc = worldChars.find(c => c.name === charName);
    const imgUrl = selectedUrl || wc.reference_image;

    // 创建内联角色标签
    const chip = document.createElement('span');
    chip.className = 'shot-inline-char-chip';

    const avatar = document.createElement('img');
    avatar.className = 'shot-inline-char-avatar';
    avatar.src = imgUrl;
    chip.appendChild(avatar);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'shot-inline-char-name';
    nameSpan.textContent = charName;
    chip.appendChild(nameSpan);

    // 点击打开图片选择器
    chip.addEventListener('click', (e) => {
      e.stopPropagation();
      showCharImageSelector(wc, charName);
    });

    displayEl.appendChild(chip);
    lastIndex = match.index + match[0].length;
  }

  // 添加剩余文本
  if(lastIndex < promptText.length) {
    displayEl.appendChild(document.createTextNode(promptText.substring(lastIndex)));
  }
}
```

**4. CSS 样式**

```css
/* 内联角色标签 */
.shot-inline-char-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px 1px 1px;
  background: #ede9fe;
  border: 1px solid #ddd6fe;
  border-radius: 12px;
  cursor: pointer;
  vertical-align: middle;
  margin: 0 2px;
}

/* 内联角色头像 */
.shot-inline-char-avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  object-fit: cover;
}

/* 内联角色名称 */
.shot-inline-char-name {
  font-size: 11px;
  color: #5b21b6;
  white-space: nowrap;
}
```

### 交互行为

1. **点击提示词区域**：打开提示词编辑模态框
2. **点击角色头像标签**：打开图片选择下拉框（复用 `showCharImageSelector`）
3. **选择图片后**：更新 `selectedCharRefImages`，刷新提示词显示，头像右上角显示 ✓ 标记
4. **无参考图时**：显示默认用户图标（👤）

### 数据流

```
提示词文本："中景：【【阿方索戴维斯_AlphonsoDavies】】深陷沙发..."
    ↓
renderPromptWithInlineChars()
    ↓
解析【【角色名】】模式
    ↓
与 state.worldCharacters 匹配获取头像
    ↓
渲染为：中景：<span class="shot-inline-char-chip">🧑 阿方索戴维斯</span>深陷沙发...
    ↓
点击头像标签 → showCharImageSelector() → 选择图片
    ↓
更新 selectedCharRefImages → 刷新提示词显示
```

## 在线缩略图服务

### API 接口

```
GET /api/thumbnail?url={图片URL}&size={尺寸}
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | 原始图片 URL（必填） | - |
| `size` | 缩略图尺寸（px） | 200 |

### 缓存策略

- **缓存目录**：`upload/cache/thumbnail/`
- **文件命名**：`{size}_{URL的MD5哈希前12位}.jpg`
- **缓存时间**：1 年（Cache-Control: immutable）

### 多进程安全

使用原子写入避免多进程冲突：

```python
def _generate_thumbnail_safe(source_path, thumb_path, size):
    # 1. 检查是否已存在
    if os.path.exists(thumb_path):
        return

    # 2. 写入临时文件（唯一名称）
    tmp_path = f"{thumb_path}.tmp.{os.getpid()}.{int(time.time())}"
    img.thumbnail((size, size), Image.LANCZOS)
    img.save(tmp_path, 'JPEG', quality=75)

    # 3. 原子重命名
    os.rename(tmp_path, thumb_path)
```

**安全保障**：
- 进程崩溃：临时文件残留，不影响下次请求
- 多进程同时写：各自写各自的临时文件，`os.rename` 是原子的
- 临时文件清理：超过 5 分钟的临时文件自动清理

### 前端调用

```javascript
// 获取缩略图URL
function getThumbnailUrl(imageUrl, size) {
    size = size || 40;
    if (!imageUrl) return '';
    if (imageUrl.startsWith('data:') || imageUrl.startsWith('blob:')) return imageUrl;
    return '/api/thumbnail?url=' + encodeURIComponent(imageUrl) + '&size=' + size;
}

// 使用示例：角色头像
avatar.src = getThumbnailUrl(imgUrl, 40);
```

### 性能优化

- 内联角色头像使用 40px 缩略图（原图可能几MB）
- 下拉选择器中的图片使用 40px 缩略图
- 添加 `loading="lazy"` 延迟加载

## 不存在角色的处理

### 问题背景
LLM 生成的剧本中可能包含数据库中不存在的角色名称（如 `【【意大利教练】】`、`【【意大利球员】】`）。如果将这些不存在的角色也渲染成带图标的标签样式，会误导用户以为这些角色已被识别和匹配。

### 解决方案
在 `renderPromptWithInlineChars` 函数中增加判断：
- **存在的角色**（`worldChars` 中有匹配）→ 渲染为带头像的标签，支持点击选择图片
- **不存在的角色** → 直接显示纯文本 `【【角色名】】`，不渲染为标签样式

### 实现代码
```javascript
const wc = worldChars.find(c => c.name === charName);

// 如果角色不存在于数据库中，直接显示纯文本
if(!wc) {
  const textNode = document.createTextNode(match[0]);
  displayEl.appendChild(textNode);
  lastIndex = match.index + match[0].length;
  continue;
}
```

### 视觉效果对比
| 场景 | 之前 | 之后 |
|------|------|------|
| 存在的角色 | 🖼️ 角色名（带头像标签） | 🖼️ 角色名（带头像标签） |
| 不存在的角色 | 👤 角色名（带默认图标） | 【【角色名】】（纯文本） |

## 注意事项

1. **角色名称格式**：系统现在会自动将 LLM 生成的名称替换为数据库中的实际名称
2. **新角色处理**：如果剧本中的角色在数据库中不存在，`character_db_id` 为 `null`，`name` 使用 LLM 生成的名称
3. **匹配精度**：匹配基于 LLM 的判断，可能存在误匹配，建议在前端提供手动修正功能
4. **性能考虑**：最多加载 50 个数据库角色，如果角色数量更多，可能需要分页加载
5. **名称备份**：LLM 生成的名称保存在 `llm_name` 字段中，便于调试和回溯
6. **不存在的角色**：数据库中不存在的角色显示为纯文本 `【【角色名】】`，不会渲染成带图标的标签，避免误导用户
