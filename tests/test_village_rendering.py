import html

import markdown

from apps.villages import views


def test_render_simple(request_context):
    rendered = views.render_markdown("Hi *you*. Welcome to [EMF](https://www.emfcamp.org/)")

    assert '<iframe sandbox="allow-scripts" ' in rendered, "iFrame should be sandboxed"
    assert "Hi &lt;em&gt;you&lt;/em&gt;." in rendered, "rendering should contain em tags"
    assert (
        "&lt;a href=&quot;https://www.emfcamp.org/&quot; rel=&quot;noopener nofollow&quot;&gt;EMF&lt;/a&gt;"
        in rendered
    ), "rendering should contain a tag"


def naive_rendering(input):
    """A naive rendering of markdown with no security used as a control for test cases."""

    extensions = ["markdown.extensions.nl2br", "markdown.extensions.smarty", "tables"]
    return html.escape(markdown.markdown(input, extensions=extensions), True)


def check_FAIL_not_rendered(input, message):
    assert "FAIL" not in views.render_markdown(input), message
    assert "FAIL" in naive_rendering(input), "Control didn't contain FAIL either for " + message


def check_FAIL_not_rendered2(input, message):
    assert "FAIL" not in views.render_markdown2(input), message
    assert "FAIL" in naive_rendering(input), "Control didn't contain FAIL either for " + message


def test_render_dangerous(request_context):
    check_FAIL_not_rendered("[click me!](javascript:alert%28'FAIL'%29)", "javascript link should be removed")
    check_FAIL_not_rendered('<script>alert("FAIL");</script>', "script tag should be removed")
    check_FAIL_not_rendered("![An Image?](/FAIL)", "CSRF img tag should be removed")
    check_FAIL_not_rendered('<img src="/FAIL"></img>', "CSRF img tag should be removed")


def test_render_image(request_context):
    check_FAIL_not_rendered("![alt text](http://example.com/FAIL.jpg)", "image should be removed")
    check_FAIL_not_rendered('<img src="http://example.com/FAIL.jpg"></img>', "CSRF img tag should be removed")


def test_render2_simple(request_context):
    rendered = views.render_markdown2("Hi *you*. Welcome to [EMF](https://www.emfcamp.org/)")

    assert "<iframe sandbox " in rendered, "iFrame should be sandboxed"
    assert "Hi &lt;em&gt;you&lt;/em&gt;." in rendered, "rendering should contain em tags"
    assert (
        "&lt;a href=&quot;https://www.emfcamp.org/&quot; rel=&quot;noopener nofollow&quot;&gt;EMF&lt;/a&gt;"
        in rendered
    ), "rendering should contain a tag"


def test_render2_dangerous(request_context):
    check_FAIL_not_rendered2("[click me!](javascript:alert%28'FAIL'%29)", "javascript link should be removed")
    check_FAIL_not_rendered2('<script>alert("FAIL");</script>', "script tag should be removed")
    check_FAIL_not_rendered2("![An Image?](/FAIL)", "CSRF img tag should be removed")
    check_FAIL_not_rendered2('<img src="/FAIL"></img>', "CSRF img tag should be removed")


def test_render2_image(request_context):
    check_FAIL_not_rendered2("![alt text](http://example.com/FAIL.jpg)", "image should be removed")
    check_FAIL_not_rendered2(
        '<img src="http://example.com/FAIL.jpg"></img>', "CSRF img tag should be removed"
    )
