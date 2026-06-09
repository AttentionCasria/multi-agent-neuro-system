import os
import jwt
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

# 配置访问地址和本地测试使用的秘钥
BASE_URL = "http://127.0.0.1:8000"
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"

def generate_test_token():
    """生成测试用的合法 JWT Token"""
    return jwt.encode({"user": "test_user"}, SECRET_KEY, algorithm=ALGORITHM)

def test_analyze():
    """测试 /ai/analyze 接口 (普通 JSON 响应)"""
    print("\n" + "="*50)
    print("🧪 测试 [健康风险分析] /ai/analyze")
    print("="*50)
    
    url = f"{BASE_URL}/ai/analyze"
    payload = {
        "patientId": 1001,
        "data": "患者男，65岁，有高血压和糖尿病史。今天早上突发言语不清，右侧肢体无力，持续约1小时未缓解。没有头痛和呕吐。",
        "token": generate_test_token()
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("✅ 请求成功！返回结果：")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        else:
            print(f"❌ 请求失败，状态码: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"⚠️ 请求异常: {e}\n(请确保先在另一个终端运行了 uvicorn main:app 或 python main.py 启动了服务器)")

def test_get_result_stream():
    """测试 /model/get_result 接口 (SSE 流式响应)"""
    print("\n" + "="*50)
    print("🧪 测试 [流式临床推理] /model/get_result")
    print("="*50)
    
    url = f"{BASE_URL}/model/get_result"
    payload = {
        "question": """
患者情况：
男性，67岁，因“突发右侧肢体完全不能活动伴言语不清2小时”由家属送至急诊。

现病史： 患者于2小时前在家中看电视时突然发病，右侧上肢及下肢均无法抬起，无法说话，但能听懂他人指令。无头痛、呕吐，无抽搐，无发热。发病后意识水平呈进行性下降，由最初清醒变为嗜睡。

既往史： 心房颤动（慢性持续性）病史10年，未规律抗凝；高血压病史15年，口服硝苯地平控释片，血压控制不详；否认糖尿病、外伤及手术史。

体格检查：

生命体征： BP 165/95 mmHg，HR 102次/分（绝对不齐），R 20次/分，T 36.5℃，SpO2 96%。

神经系统：

意识：嗜睡，强刺激可唤醒，配合检查较差。

凝视：双眼向左侧凝视。

面部：右侧鼻唇沟浅。

运动：右侧上肢肌力0级，下肢肌力1级；左侧肢体肌力5级。

感觉：右侧针刺觉减退。

共济：因肌力无法配合。

语言：完全性失语（表达与理解均严重受损）。

NIHSS评分： 估计为 18-20分（提示大血管闭塞可能性大）。

辅助检查（急诊床旁）：

血糖： 6.2 mmol/L。

心电图： 心房颤动（心室率约110次/分）。

头颅CT平扫（发病后2.5小时）： 脑实质未见明确高密度出血灶；左侧大脑中动脉（MCA）区域可见早期缺血改变：岛叶皮质灰白质交界消失，豆状核模糊；尚未见明显低密度灶。ASPECTS评分（Alberta卒中项目早期CT评分）为 8分。

需要回答的核心问题：
初步诊断与鉴别诊断：

该患者最可能的TOAST病因分型是什么？依据是什么？

需要与哪些疾病进行鉴别（至少列出2个）？

影像学决策：

虽然平扫CT已排除出血，患者处于时间窗内，但临床高度怀疑大血管闭塞。此时，是否需要进一步进行 CTA（CT血管成像） 和 CTP（CT灌注成像）？请阐述理由（即“组织窗”优于“时间窗”的概念在此患者中的应用价值）。

急性期治疗决策（核心问题）：

问题A（静脉溶栓）： 该患者是否符合静脉溶栓（rt-PA，阿替普酶）指征？是否存在绝对禁忌症？若符合，请给出具体剂量和给药方式。

问题B（血管内治疗/取栓）： 基于患者目前的临床特征（高NIHSS评分、房颤史、ASPECTS 8分），您是否建议立即启动 血管内机械取栓？为什么？

问题C（治疗顺序）： 如果患者同时符合静脉溶栓和机械取栓的条件，您认为应该“桥接治疗”（先溶栓后取栓）还是“直接取栓”？当前指南更推荐哪种策略？

围治疗期管理：

在溶栓/取栓过程中及术后24小时内，血压应该控制在什么目标水平？

患者术后次日复查头颅CT显示梗死灶内出现点状高密度影，无占位效应，患者症状稳定。这最可能是什么？是否需要特殊处理？""",
        "round": 1,
        "all_info": "",
        "token": generate_test_token(),
        "report_mode": "fast",
        "show_thinking": True
    }
    
    try:
        # stream=True 是因为接受的是 SSE (Server-Sent Events) 流式数据
        response = requests.post(url, json=payload, stream=True)
        
        if response.status_code != 200:
            print(f"❌ 请求失败，状态码: {response.status_code}, {response.text}")
            return
            
        print("✅ 连接建立，开始接收数据流...")
        
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                # SSE 格式是以 "data: " 开头的 JSON 字符串
                if decoded_line.startswith("data:"):
                    data_str = decoded_line[5:].strip()
                    try:
                        data = json.loads(data_str)
                        # 判断返回的 SSE 事件类型并打印
                        event_type = data.get("type")
                        
                        if event_type == "node_start":
                            print(f"\n[🔄 节点开始] {data.get('node')} - {data.get('label')}")
                        elif event_type == "thinking":
                            # 为了排版好看，不用每次换行
                            print(data.get("content", ""), end="", flush=True)
                        elif event_type == "token":
                            print(data.get("content", ""), end="", flush=True)
                        elif event_type == "done":
                            print(f"\n\n[🏁 处理完毕] 自动命名标签: {data.get('name')}")
                        elif event_type == "error":
                            print(f"\n[❌ 错误发生] {data.get('message')}")
                            
                    except json.JSONDecodeError:
                        print(f"\n[未解析文本] {data_str}")
        print("\n--- 流式接收结束 ---")
        
    except Exception as e:
        print(f"⚠️ 请求异常: {e}\n(请确保您的服务器在运行中)")

def test_pubmed_search():
    """测试 /model/pubmed/search 接口"""
    print("\n" + "="*50)
    print("🧪 测试 [PubMed 文献检索] /model/pubmed/search")
    print("="*50)
    
    url = f"{BASE_URL}/model/pubmed/search"
    payload = {
        "query": "Stroke thrombolysis",
        "max_results": 2
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("✅ 请求成功！返回结果摘要：")
            data = response.json().get("data", {}).get("papers", [])
            for i, p in enumerate(data, 1):
                print(f"{i}. {p.get('title')} ({p.get('pub_date')})")
        else:
            print(f"❌ 请求失败，状态码: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"⚠️ 请求异常: {e}")

def test_quick_analyze():
    """测试 /ai/quick-analyze 接口（快速AI意见）"""
    print("\n" + "="*50)
    print("⚡ 测试 [快速AI意见] /ai/quick-analyze")
    print("="*50)
    
    url = f"{BASE_URL}/ai/quick-analyze"
    payload = {
        "question": "患者术后次日复查头颅CT显示梗死灶内出现点状高密度影，无占位效应，患者症状稳定。这最可能是什么？是否需要特殊处理？",
        "token": generate_test_token()
    }
    
    try:
        start_time = time.time()
        response = requests.post(url, json=payload)
        elapsed_time = time.time() - start_time
        
        if response.status_code == 200:
            print(f"✅ 请求成功！耗时: {elapsed_time:.2f}秒")
            print("返回结果：")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        else:
            print(f"❌ 请求失败，状态码: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"⚠️ 请求异常: {e}\n(请确保您的服务器在运行中)")

if __name__ == "__main__":
    print("🔔 运行测试前，请确保主服务已经在另一个终端中通过 `python main.py` 启动工作，监听 8000 端口。")
    print("按需取消注释对应你想测试的函数:")
    
    # 1. 测试常规的健康风险分析
    test_analyze()
    
    # 2. 测试最核心的 RAG 模型综合流式推断
    test_get_result_stream()
    
    # 3. 测试外部文献的检索接口
    test_pubmed_search()