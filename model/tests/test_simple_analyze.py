"""
简单的接口测试脚本
测试优化后的 /ai/analyze 接口
"""
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_analyze():
    """测试健康风险分析接口"""
    print("\n" + "="*80)
    print("🏥 测试优化后的 /ai/analyze 接口")
    print("="*80)
    
    url = f"{BASE_URL}/ai/analyze"
    
    payload = {
        "patientId": 1,
        "data": "患者男，65岁，有高血压和糖尿病史。今天早上突发言语不清，右侧肢体无力，持续约1小时未缓解。"
    }
    
    print(f"📝 请求参数:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("-" * 80)
    
    try:
        start_time = time.time()
        
        response = requests.post(url, json=payload)
        elapsed_time = time.time() - start_time
        
        print(f"⏱️  耗时: {elapsed_time:.2f}秒")
        print(f"📊 状态码: {response.status_code}")
        
        if response.status_code == 200:
            print("\n✅ 请求成功！返回结果：")
            result = response.json()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # 速度评级
            if elapsed_time < 1.5:
                speed_rating = "🚀 极快"
            elif elapsed_time < 2.5:
                speed_rating = "⚡ 快速"
            elif elapsed_time < 4:
                speed_rating = "🐢 一般"
            else:
                speed_rating = "🐌 慢"
            
            print(f"\n📈 速度评级: {speed_rating}")
            print("\n🎉 接口优化成功！")
        else:
            print(f"\n❌ 请求失败")
            print(f"错误信息: {response.text}")
            
    except Exception as e:
        print(f"\n⚠️ 请求异常: {e}")
        print("请确保服务器正在运行: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")

if __name__ == "__main__":
    test_analyze()