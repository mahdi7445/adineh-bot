"""تولید DATA_KEY (کلید رمزنگاری). فقط یک‌بار اجرا کنید و کلید را در جای امن (مثلاً مدیریت رمز) نگه دارید.
اگر این کلید گم شود، اطلاعات رمزنگاری‌شده و پشتیبان‌ها قابل بازیابی نیستند."""
from cryptography.fernet import Fernet

print("DATA_KEY=" + Fernet.generate_key().decode())
