"""Tests for volunteer schedule filter visibility."""


def test_show_my_shifts_filter_hidden_for_admin():
    """Volunteer admins should not see the 'Show my shifts' filter."""
    from main import create_app

    app = create_app()
    with app.test_request_context("/"):
        from flask import render_template_string

        result = render_template_string(
            "{% from 'volunteer/_schedule_filters.html' import vol_schedule_filters %}"
            "{{ vol_schedule_filters([], is_admin=True) }}"
        )
        assert "show_signed_up_only" not in result


def test_show_my_shifts_filter_visible_for_non_admin():
    """Regular volunteers should see the 'Show my shifts' filter."""
    from main import create_app

    app = create_app()
    with app.test_request_context("/"):
        from flask import render_template_string

        result = render_template_string(
            "{% from 'volunteer/_schedule_filters.html' import vol_schedule_filters %}"
            "{{ vol_schedule_filters([], is_admin=False) }}"
        )
        assert "show_signed_up_only" in result
