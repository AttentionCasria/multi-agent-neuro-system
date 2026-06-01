import os
import jwt
import json
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
        "question": "对于发病4.5小时内的急性缺血性卒中患者，如果既往有颅内出血史或者正在服用直接口服抗凝药（DOACs），该怎么办？",
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

if __name__ == "__main__":
    print("🔔 运行测试前，请确保主服务已经在另一个终端中通过 `python main.py` 启动工作，监听 8000 端口。")
    print("按需取消注释对应你想测试的函数:")
    
    # 1. 测试常规的健康风险分析
    test_analyze()
    
    # 2. 测试最核心的 RAG 模型综合流式推断
    test_get_result_stream()
    
    # 3. 测试外部文献的检索接口
    test_pubmed_search()
