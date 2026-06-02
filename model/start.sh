#!/bin/bash

echo "========================================"
echo "临床推理系统 - 快速启动脚本"
echo "========================================"
echo ""

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未检测到Python，请先安装Python 3.10或更高版本"
    exit 1
fi

echo "✅ Python环境检测通过"
python3 --version
echo ""

# 检查虚拟环境
if [ -d "venv" ]; then
    echo "✅ 检测到虚拟环境，正在激活..."
    source venv/bin/activate
else
    echo "⚠️  未检测到虚拟环境"
    read -p "是否创建虚拟环境? (y/n): " create_venv
    if [ "$create_venv" = "y" ]; then
        echo "正在创建虚拟环境..."
        python3 -m venv venv
        source venv/bin/activate
        echo "✅ 虚拟环境创建成功"
    else
        echo "⚠️  跳过虚拟环境创建"
    fi
fi
echo ""

# 检查依赖
echo "检查依赖包..."
if ! pip show langgraph &> /dev/null; then
    echo "⚠️  依赖包未安装，正在安装..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ 依赖安装失败"
        exit 1
    fi
    echo "✅ 依赖安装成功"
else
    echo "✅ 依赖包已安装"
fi
echo ""

# 检查配置文件
echo "检查配置文件..."
if [ ! -f ".env" ]; then
    echo "❌ 错误: .env 文件不存在"
    echo "请先创建 .env 文件并配置API密钥"
    echo ""
    echo "示例 .env 内容:"
    echo "DASHSCOPE_API_KEY=sk-your-api-key-here"
    echo "SECRET_KEY=your-secret-key-here"
    exit 1
fi
echo "✅ 配置文件检测通过"
echo ""

# 运行配置测试
echo "运行配置测试..."
python test_config_optimization.py
if [ $? -ne 0 ]; then
    echo "⚠️  配置测试失败，但继续启动..."
else
    echo "✅ 配置测试通过"
fi
echo ""

# 启动服务
echo "========================================"
echo "正在启动服务..."
echo "========================================"
echo ""
echo "服务地址: http://localhost:8000"
echo "API文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止服务"
echo "========================================"
echo ""

python app/main.py