"""
测试 /ai/analyze 接口
按照接口规范测试健康风险分析
"""
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_analyze():
    """测试 /ai/analyze 接口"""
    print("\n" + "="*50)
    print("🏥 测试 [健康风险分析] /ai/analyze")
    print("="*50)
    
    url = f"{BASE_URL}/ai/analyze"
    
    # 按照接口规范的请求参数
    payload = {
        "patientId": 1,
        "data": "患者男，65岁，有高血压和糖尿病史。今天早上突发言语不清，右侧肢体无力，持续约1小时未缓解。没有头痛和呕吐。"
    }
    
    print(f"📝 请求参数:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("-" * 50)
    
    try:
        import time
        start_time = time.time()
        
        response = requests.post(url, json=payload)
        elapsed_time = time.time() - start_time
        
        print(f"⏱️  耗时: {elapsed_time:.2f}秒")
        print(f"📊 状态码: {response.status_code}")
        
        if response.status_code == 200:
            print("\n✅ 请求成功！返回结果：")
            result = response.json()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # 验证响应格式
            if result.get("code") == 1 and result.get("msg") == "success":
                data = result.get("data", {})
                print("\n📋 解析结果:")
                print(f"  风险等级: {data.get('riskLevel')}")
                print(f"  建议: {data.get('suggestion')}")
                print(f"  分析详情: {data.get('analysisDetails')}")
                print("\n🎉 接口格式验证通过！")
            else:
                print("\n⚠️  响应格式不符合预期")
        else:
            print(f"\n❌ 请求失败")
            print(f"错误信息: {response.text}")
            
    except Exception as e:
        print(f"\n⚠️ 请求异常: {e}")
        print("请确保服务器正在运行: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")

if __name__ == "__main__":
    test_analyze()