from test_controller import command, execute


def test_replayed_stop_also_latches_current_run_state(controller, recipe):
    c = controller
    c.new_session(recipe)
    stop = command(c, "stop")
    c.command(stop, "test")
    c.command(command(c, "start"), "test")
    assert c.session["phase"] == "READY"
    assert c.command(stop, "test")["duplicate"]
    assert c.session["phase"] == "PAUSED"


def test_stop_after_pass_can_resume_departure_without_recount(controller, recipe):
    c = controller
    c.new_session(recipe)
    execute(c, recipe)
    c.command(command(c, "pause"), "test")
    c.command(command(c, "start"), "test")
    assert c.session["phase"] == "PASSED" and c.session["count"] == 1
    c.command(command(c, "release"), "test")
    assert c.session["active_product"] is None
