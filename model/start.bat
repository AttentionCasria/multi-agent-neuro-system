@echo off
chcp 65001 > nul
echo ========================================
echo 临床推理系统 - 快速启动脚本
echo ========================================
echo.

REM 检查Python是否安装
python --version > nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: 未检测到Python，请先安装Python 3.10或更高版本
    pause
    exit /b 1
)

echo ✅ Python环境检测通过
echo.

REM 检查虚拟环境
if exist "venv\Scripts\activate.bat" (
    echo ✅ 检测到虚拟环境，正在激活...
    call venv\Scripts\activate.bat
) else (
    echo ⚠️  未检测到虚拟环境
    echo.
    set /p create_venv="是否创建虚拟环境? (y/n): "
    if /i "%create_venv%"=="y" (
        echo 正在创建虚拟环境...
        python -m venv venv
        call venv\Scripts\activate.bat
        echo ✅ 虚拟环境创建成功
    ) else (
        echo ⚠️  跳过虚拟环境创建
    )
)
echo.

REM 检查依赖
echo 检查依赖包...
pip show langgraph > nul 2>&1
if errorlevel 1 (
    echo ⚠️  依赖包未安装，正在安装...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ❌ 依赖安装失败
        pause
        exit /b 1
    )
    echo ✅ 依赖安装成功
) else (
    echo ✅ 依赖包已安装
)
echo.

REM 检查配置文件
echo 检查配置文件...
if not exist ".env" (
    echo ❌ 错误: .env 文件不存在
    echo 请先创建 .env 文件并配置API密钥
    echo.
    echo 示例 .env 内容:
    echo DASHSCOPE_API_KEY=sk-your-api-key-here
    echo SECRET_KEY=your-secret-key-here
    pause
    exit /b 1
)
echo ✅ 配置文件检测通过
echo.

REM 运行配置测试
echo 运行配置测试...
python test_config_optimization.py
if errorlevel 1 (
    echo ⚠️  配置测试失败，但继续启动...
) else (
    echo ✅ 配置测试通过
)
echo.

REM 启动服务
echo ========================================
echo 正在启动服务...
echo ========================================
echo.
echo 服务地址: http://localhost:8000
echo API文档: http://localhost:8000/docs
echo.
echo 按 Ctrl+C 停止服务
echo ========================================
echo.

python app/main.py

pause