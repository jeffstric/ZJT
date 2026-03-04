#!/usr/bin/env python3
"""
七牛云对象存储上传功能测试
"""

import qiniu
import requests


# 七牛云配置
QINIU_ACCESS_KEY = "IAM-0fZBG5O0nEj9Xy-d_vjtowNp4viwWmjaDx8tNjCY"
QINIU_SECRET_KEY = "HD3mwsOHnr5uSjPRTyvIWDrmwCEfOUlwQiT5HhNft9TB"
QINIU_BUCKET_NAME = "jeffstric"
QINIU_CDN_DOMAIN = "cdn.perseids.cn"


def test_upload_text():
    """测试上传文本数据"""
    print("=" * 50)
    print("测试1: 上传文本数据")
    print("=" * 50)

    q = qiniu.Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY)
    key = "test/hello.txt"
    data = "hello qiniu!"
    token = q.upload_token(QINIU_BUCKET_NAME)

    ret, info = qiniu.put_data(token, key, data.encode("utf-8"))

    print(f"返回结果: {ret}")
    print(f"返回信息: {info}")

    if ret is not None:
        print("✅ 上传成功!")
        print(f"文件Key: {ret.get('key')}")
        print(f"文件Hash: {ret.get('hash')}")
    else:
        print("❌ 上传失败!")
        print(f"错误信息: {info}")

    return ret is not None


def test_upload_file():
    """测试上传本地文件"""
    print("\n" + "=" * 50)
    print("测试2: 上传本地文件")
    print("=" * 50)

    q = qiniu.Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY)

    # 创建一个测试文件
    test_file_path = "test_upload_file.txt"
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write("这是一个测试文件内容\n")
        f.write("用于测试七牛云文件上传功能\n")

    key = "test/test_file.txt"
    token = q.upload_token(QINIU_BUCKET_NAME, key)

    ret, info = qiniu.put_file(token, key, test_file_path)

    print(f"返回结果: {ret}")
    print(f"返回信息: {info}")

    if ret is not None:
        print("✅ 文件上传成功!")
        print(f"文件Key: {ret.get('key')}")
        print(f"文件Hash: {ret.get('hash')}")
    else:
        print("❌ 文件上传失败!")
        print(f"错误信息: {info}")

    # 清理测试文件
    import os
    os.remove(test_file_path)
    print(f"已清理临时文件: {test_file_path}")

    return ret is not None


def test_upload_with_custom_key():
    """测试使用自定义key上传"""
    print("\n" + "=" * 50)
    print("测试3: 自定义Key上传")
    print("=" * 50)

    q = qiniu.Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY)

    import time
    timestamp = int(time.time())
    key = f"test/custom_key_{timestamp}.txt"
    data = f"自定义key测试 - 时间戳: {timestamp}"

    token = q.upload_token(QINIU_BUCKET_NAME, key)
    ret, info = qiniu.put_data(token, key, data.encode("utf-8"))

    print(f"自定义Key: {key}")
    print(f"返回结果: {ret}")
    print(f"返回信息: {info}")

    if ret is not None:
        print("✅ 自定义Key上传成功!")
        print(f"文件Key: {ret.get('key')}")
    else:
        print("❌ 自定义Key上传失败!")
        print(f"错误信息: {info}")

    return ret is not None


def test_download_file():
    """测试下载文件(私有链接)"""
    print("\n" + "=" * 50)
    print("测试4: 文件下载(私有链接)")
    print("=" * 50)

    q = qiniu.Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY)

    # 先上传一个测试文件
    key = "test/download_test.txt"
    data = "这是用于测试下载的文件内容"
    token = q.upload_token(QINIU_BUCKET_NAME)
    ret, info = qiniu.put_data(token, key, data.encode("utf-8"))

    if ret is None:
        print("❌ 上传测试文件失败,无法进行下载测试")
        return False

    print(f"✅ 测试文件上传成功: {key}")

    # 构造下载URL
    base_url = f"http://{QINIU_CDN_DOMAIN}/{key}"
    print(f"Base URL: {base_url}")

    # 生成私有下载链接(有效期1小时)
    private_url = q.private_download_url(base_url, expires=3600)
    print(f"私有下载链接已生成(有效期1小时)")

    # 下载文件
    try:
        r = requests.get(private_url)
        print(f"私有下载链接: {private_url}")
        print(f"HTTP状态码: {r.status_code}")

        if r.status_code == 200:
            # 设置正确的编码
            r.encoding = 'utf-8'
            downloaded_content = r.text
            print(f"下载内容: {downloaded_content}")

            if downloaded_content == data:
                print("✅ 文件下载成功,内容验证通过!")
                return True
            else:
                print("❌ 文件下载成功,但内容不匹配")
                print(f"原始内容: {data}")
                print(f"下载内容: {downloaded_content}")
                return False
        else:
            print(f"❌ 文件下载失败: HTTP {r.status_code}")
            print(f"响应内容: {r.text}")
            return False
    except Exception as e:
        print(f"❌ 下载过程出现异常: {e}")
        return False


def test_public_download():
    """测试公开访问(如果bucket是公开的)"""
    print("\n" + "=" * 50)
    print("测试5: 公开访问测试")
    print("=" * 50)

    # 尝试直接访问已上传的文件
    key = "test/hello.txt"
    public_url = f"http://{QINIU_CDN_DOMAIN}/{key}"

    print(f"公开URL: {public_url}")

    try:
        r = requests.get(public_url)
        print(f"HTTP状态码: {r.status_code}")

        if r.status_code == 200:
            print(f"下载内容: {r.text}")
            print("✅ 公开访问成功(Bucket为公开)")
            return True
        elif r.status_code == 403:
            print("✅ Bucket为私有,需要私有下载链接(预期行为)")
            return True
        else:
            print(f"⚠️  访问返回状态码: {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ 访问异常: {e}")
        return False


def test_upload_image():
    """测试上传图片文件"""
    print("\n" + "=" * 50)
    print("测试6: 上传图片文件")
    print("=" * 50)

    import os

    # 图片文件路径
    image_path = "files/二维码.jpg"

    # 检查文件是否存在
    if not os.path.exists(image_path):
        print(f"❌ 图片文件不存在: {image_path}")
        return False

    print(f"找到图片文件: {image_path}")
    print(f"文件大小: {os.path.getsize(image_path)} bytes")

    q = qiniu.Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY)

    # 使用图片文件名作为key
    key = "test/二维码.jpg"
    token = q.upload_token(QINIU_BUCKET_NAME, key)

    ret, info = qiniu.put_file(token, key, image_path)

    print(f"返回结果: {ret}")
    print(f"返回信息: {info}")

    if ret is not None:
        print("✅ 图片上传成功!")
        print(f"文件Key: {ret.get('key')}")
        print(f"文件Hash: {ret.get('hash')}")

        # 生成私有下载链接
        base_url = f"http://{QINIU_CDN_DOMAIN}/{key}"
        private_url = q.private_download_url(base_url, expires=3600)
        print(f"\n图片私有下载链接(有效期1小时):")
        print(private_url)

        # 使用私有链接下载图片并验证
        print("\n正在使用私有链接下载图片...")
        try:
            r = requests.get(private_url)
            print(f"HTTP状态码: {r.status_code}")

            if r.status_code == 200:
                # 获取原始文件大小
                original_size = os.path.getsize(image_path)
                downloaded_size = len(r.content)
                print(f"原始文件大小: {original_size} bytes")
                print(f"下载文件大小: {downloaded_size} bytes")

                if original_size == downloaded_size:
                    print("✅ 图片下载成功,文件大小验证通过!")
                else:
                    print("⚠️  文件大小不匹配,但下载成功")

                # 保存下载的图片到临时文件
                downloaded_path = "files/二维码_downloaded.jpg"
                with open(downloaded_path, "wb") as f:
                    f.write(r.content)
                print(f"✅ 下载的图片已保存到: {downloaded_path}")
            else:
                print(f"❌ 图片下载失败: HTTP {r.status_code}")
        except Exception as e:
            print(f"❌ 下载过程出现异常: {e}")

        return True
    else:
        print("❌ 图片上传失败!")
        print(f"错误信息: {info}")
        return False


def main():
    """主函数：运行所有测试"""
    print("\n" + "#" * 60)
    print("# 七牛云对象存储上传功能测试")
    print("#" * 60)
    print(f"Bucket名称: {QINIU_BUCKET_NAME}")

    results = []

    try:
        results.append(("上传文本数据", test_upload_text()))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("上传文本数据", False))

    try:
        results.append(("上传本地文件", test_upload_file()))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("上传本地文件", False))

    try:
        results.append(("自定义Key上传", test_upload_with_custom_key()))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("自定义Key上传", False))

    try:
        results.append(("文件下载(私有链接)", test_download_file()))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("文件下载(私有链接)", False))

    try:
        results.append(("公开访问测试", test_public_download()))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("公开访问测试", False))

    try:
        results.append(("上传图片文件", test_upload_image()))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("上传图片文件", False))

    # 打印测试总结
    print("\n" + "#" * 60)
    print("# 测试结果总结")
    print("#" * 60)
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")

    total = len(results)
    passed = sum(1 for _, r in results if r)
    print(f"\n总计: {passed}/{total} 个测试通过")

    return passed == total


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
