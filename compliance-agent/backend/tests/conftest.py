"""测试夹具：用临时目录隔离数据库与对象存储，全部走离线实现。"""
import os
import tempfile

# 必须在导入 app 之前设置环境变量
_TMP = tempfile.mkdtemp(prefix="compliance_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/storage"
os.environ["LLM_PROVIDER"] = "stub"
os.environ["EMBEDDER"] = "stub"
os.environ["VECTOR_STORE"] = "memory"
