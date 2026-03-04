#!/bin/bash

# 视频驱动数据库集成测试运行脚本

source /home/appuser/miniconda3/etc/profile.d/conda.sh
conda activate comfyui_server

echo "=========================================="
echo "视频驱动数据库集成测试"
echo "=========================================="
echo ""

echo "运行所有驱动的数据库集成测试..."
echo ""

python3 -m unittest \
    tests.driver_integration.test_vidu_driver_with_db \
    tests.driver_integration.test_ltx2_driver_with_db \
    tests.driver_integration.test_kling_driver_with_db \
    tests.driver_integration.test_digital_human_driver_with_db \
    tests.driver_integration.test_gemini_driver_with_db \
    tests.driver_integration.test_gemini_pro_driver_with_db \
    tests.driver_integration.test_sora2_driver_with_db \
    tests.driver_integration.test_veo3_driver_with_db \
    tests.driver_integration.test_wan22_driver_with_db \
    -v

echo ""
echo "=========================================="
echo "测试完成"
echo "=========================================="
