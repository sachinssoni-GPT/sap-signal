from sapsignal.research.page_fetcher import _is_public_http_url


def test_rejects_private_and_local_addresses():
    assert not _is_public_http_url("http://127.0.0.1/admin")
    assert not _is_public_http_url("http://10.0.0.5/")
    assert not _is_public_http_url("http://192.168.1.10/")
    assert not _is_public_http_url("http://169.254.169.254/latest/meta-data/")


def test_rejects_non_http_and_embedded_credentials():
    assert not _is_public_http_url("file:///etc/passwd")
    assert not _is_public_http_url("https://user:pass@example.com/")


def test_rejects_invalid_url():
    assert not _is_public_http_url("not a url")
