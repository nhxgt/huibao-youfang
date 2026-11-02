"""Validation for opaque API tokens used in an HTTP Authorization header."""

INVALID_KEY_MESSAGE = "API Key 格式无效，请从模型服务商复制真实密钥，不要填写中文、空格或密码遮罩。"


def valid_api_key(value):
    # Keep provider-specific prefixes unrestricted, but reject values that cannot
    # form a printable ASCII token or are just a password field's mask.
    return (isinstance(value, str) and 1 <= len(value) <= 4096 and
            all(0x21 <= ord(char) <= 0x7E for char in value) and
            any(char != "*" for char in value))
