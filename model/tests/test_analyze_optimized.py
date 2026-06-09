"""
测试流程优化后的 /ai/analyze 接口
对比优化前后的性能差异
"""
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_analyze_optimized():
    """测试优化后的接口"""
    print("\n" + "="*80)
    print("🚀 测试流程优化后的 /ai/analyze 接口")
    print("="*80)
    
    url = f"{BASE_URL}/ai/analyze"
    
    # 测试用例
    test_cases = [
        {
            "patientId": 1,
            "data": "患者男，65岁，有高血压和糖尿病史。今天早上突发言语不清，右侧肢体无力，持续约1小时未缓解。"
        },
        {
            "patientId": 2,
            "data": "患者女，45岁，体检发现血压偏高，无明显症状。"
        },
        {
            "patientId": 3,
            "data": "患者男，30岁，健康体检，各项指标正常。"
        }
    ]
    
    results = []
    
    for i, payload in enumerate(test_cases, 1):
        print(f"\n📋 测试用例 {i}:")
        print(f"   患者ID: {payload['patientId']}")
        print(f"   数据: {payload['data'][:50]}...")
        print("-" * 80)
        
        try:
            start_time = time.time()
            
            response = requests.post(url, json=payload)
            elapsed_time = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                data = result.get("data", {})
                
                print(f"⏱️  耗时: {elapsed_time:.2f}秒")
                print(f"🎯 风险等级: {data.get('riskLevel')}")
                print(f"💡 建议: {data.get('suggestion')}")
                print(f"📊 分析详情: {data.get('analysisDetails')}")
                
                # 速度评级
                if elapsed_time < 1.5:
                    speed_rating = "🚀 极快"
                elif elapsed_time < 2.5:
                    speed_rating = "⚡ 快速"
                elif elapsed_time < 4:
                    speed_rating = "🐢 一般"
                else:
                    speed_rating = "🐌 慢"
                
                print(f"📈 速度评级: {speed_rating}")
                
                results.append({
                    "case": i,
                    "time": elapsed_time,
                    "success": True
                })
            else:
                print(f"❌ 请求失败: {response.status_code}")
                print(f"错误信息: {response.text}")
                results.append({
                    "case": i,
                    "time": 0,
                    "success": False
                })
                
        except Exception as e:
            print(f"❌ 请求异常: {e}")
            results.append({
                "case": i,
                "time": 0,
                "success": False
            })
    
    # 统计结果
    print("\n" + "="*80)
    print("📊 性能统计")
    print("="*80)
    
    successful_results = [r for r in results if r["success"]]
    if successful_results:
        avg_time = sum(r["time"] for r in successful_results) / len(successful_results)
        min_time = min(r["time"] for r in successful_results)
        max_time = max(r["time"] for r in successful_results)
        
        print(f"✅ 成功: {len(successful_results)}/{len(results)}")
        print(f"⏱️  平均耗时: {avg_time:.2f}秒")
        print(f"⏱️  最快: {min_time:.2f}秒")
        print(f"⏱️  最慢: {max_time:.2f}秒")
        
        # 性能评级
        if avg_time < 2:
            performance = "🚀 优秀"
        elif avg_time < 3:
            performance = "⚡ 良好"
        elif avg_time < 5:
            performance = "🐢 一般"
        else:
            performance = "🐌 需要优化"
        
        print(f"📈 性能评级: {performance}")
    else:
        print("❌ 所有测试失败")
    
    print("="*80)
    print("🎉 测试完成！")
    print("="*80)

if __name__ == "__main__":
    test_analyze_optimized()