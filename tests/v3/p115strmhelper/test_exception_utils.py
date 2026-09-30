"""115 网盘 STRM 助手：通知异常格式化单测。

``NotifyExceptionFormatter`` 把底层异常折成一段适合推送的短文本。
用例锁住两类输入形态：带 code/reason/message 属性的异常，以及需要从
字符串里正则提取字段的异常。
"""
from app.plugins.p115strmhelper.utils.exception import NotifyExceptionFormatter


class _HttpAttrError(Exception):
    """同时带 code / reason / message 属性的伪 HTTP 异常。"""

    def __init__(self, code=None, reason=None, message=None):
        super().__init__("boom")
        self.code = code
        self.reason = reason
        self.message = message


def test_attr_error_renders_code_and_reason():
    """属性齐全时按「HTTP 码（原因）：消息」拼接。"""
    exc = _HttpAttrError(code=500, reason="Internal Server Error", message="upstream down")
    assert NotifyExceptionFormatter.format_exception_for_notify(exc) == (
        "HTTP 500（Internal Server Error）：upstream down"
    )


def test_attr_error_code_only():
    """只有状态码时仅输出状态码文本。"""
    assert NotifyExceptionFormatter.format_exception_for_notify(_HttpAttrError(code=404)) == "HTTP 404"


def test_attr_error_reason_only_uses_fallback_prefix():
    """无状态码但有原因时，前缀回退为「请求错误」。"""
    exc = _HttpAttrError(reason="timeout")
    assert NotifyExceptionFormatter.format_exception_for_notify(exc) == "请求错误（timeout）"


def test_status_code_attribute_is_accepted_as_alias():
    """status_code 与 code 等价，不应被忽略。"""
    class _AliasError(Exception):
        """只提供 status_code 的伪异常。"""

        def __init__(self):
            super().__init__("boom")
            self.status_code = 403

    assert NotifyExceptionFormatter.format_exception_for_notify(_AliasError()) == "HTTP 403"


def test_string_form_error_is_parsed_by_regex():
    """文本里带 code=/reason=/message= 时按正则提取后重排。"""
    exc = ValueError("code=502 reason='Bad Gateway' message='please retry'")
    assert NotifyExceptionFormatter.format_exception_for_notify(exc) == (
        "HTTP 502（Bad Gateway）：please retry"
    )


def test_empty_message_falls_back_to_type_name():
    """空消息退化为异常类名，避免推送空白通知。"""
    assert NotifyExceptionFormatter.format_exception_for_notify(Exception()) == "Exception"


def test_plain_exception_is_prefixed_with_type_name():
    """普通异常保留原文，并前置异常类名以便定位。"""
    formatted = NotifyExceptionFormatter.format_exception_for_notify(RuntimeError("disk full"))
    assert formatted == "RuntimeError: disk full"


def test_result_is_length_capped():
    """超长文本按 max_length 截断，保证通知不至于刷屏。"""
    exc = RuntimeError("x" * 5000)
    assert len(NotifyExceptionFormatter.format_exception_for_notify(exc, max_length=200)) == 200
