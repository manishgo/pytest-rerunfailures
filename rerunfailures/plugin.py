import sys, time
import py, pytest
import copy

from _pytest.runner import call_and_report

# command line options
def pytest_addoption(parser):
	group = parser.getgroup("rerunfailures", "re-run failing tests to eliminate flakey failures")
	group._addoption('--reruns',
			action="store",
			dest="reruns",
			type="int",
			default=0,
			help="number of times to re-run failed tests. defaults to 0.")

	# making sure the options make sense
# should run before / at the begining of pytest_cmdline_main
def check_options(config):
	val = config.getvalue
	if not val("collectonly"):
		if config.option.reruns != 0:
			if config.option.usepdb:   # a core option
				raise pytest.UsageError("--reruns incompatible with --pdb")

def clear_errors(item):
	for call in item.listchain():
		hasattr(call,'_prepare_exc') and delattr(call,'_prepare_exc')

def has_setup_class_failed(callstack,item):
	for call in callstack:
		if item.parent.name == call.name and hasattr(call,'_prepare_exc'):
			return True
	return False


def runtestprotocol(item, log=True, nextitem=None,is_last_run=True):
	rep = call_and_report(item, "setup", log)
	reports = [rep]
	if rep.passed:
		reports.append(call_and_report(item, "call", log))
	if not reports[0].passed or not reports[1].passed:
		if nextitem == None and not is_last_run:
			callstack = item.session._setupstate.stack
			last_index = len(callstack)-1
			if last_index>=0 and item.name == callstack[last_index].name:  
				try:
					item.session._setupstate._teardown_towards(item.listchain()[:last_index])
				except:
					pass
				return reports
	reports.append(call_and_report(item, "teardown", log,nextitem=nextitem))
	return reports

def pytest_runtest_protocol(item, nextitem):
	"""
	Note: when teardown fails, two reports are generated for the case, one for the test
	case and the other for the teardown error.

	Note: in some versions of py.test, when setup fails on a test that has been marked with xfail,
	it gets an XPASS rather than an XFAIL
	(https://bitbucket.org/hpk42/pytest/issue/160/an-exception-thrown-in)
	fix should be released in version 2.2.5
	"""
	reruns = item.session.config.option.reruns
	if reruns ==0 or hasattr(item.session,'has_setup_failed'):
		return
	# while this doesn't need to be run with every item, it will fail on the first
	# item if necessary
	check_options(item.session.config)

	item.ihook.pytest_runtest_logstart(
		nodeid=item.nodeid, location=item.location
	)

	for i in range(reruns+1):  # ensure at least one run of each item
		reports = runtestprotocol(item, nextitem=nextitem, log=False,is_last_run=(i==reruns))
		callstack = item.session._setupstate.stack
		# break if setup and call pass
		if reports[0].failed:
			if has_setup_class_failed(callstack,item):
				if i<reruns:
					clear_errors(item)
					reports[1]=call_and_report(item, "teardown", log=False,nextitem=None)
				else:
					item.session.has_setup_failed = True
			else:
				clear_errors(item)
		elif reports[1].failed and 'AssertionError' in reports[1].longrepr.reprcrash.message:
			break

		if reports[0].passed and reports[1].passed:
			break

		# break if test marked xfail
		evalxfail = getattr(item, '_evalxfail', None)
		if evalxfail:
			break

	for report in reports:
		if report.when in ("call"):
			if i > 0:
				report.rerun = i
		item.ihook.pytest_runtest_logreport(report=report)

	# pytest_runtest_protocol returns True
	return True


def pytest_report_teststatus(report):
	""" adapted from
	https://bitbucket.org/hpk42/pytest/src/a5e7a5fa3c7e/_pytest/skipping.py#cl-170
	"""
	if report.when in ("call"):
		if hasattr(report, "rerun") and report.rerun > 0:
			if report.outcome == "failed":
				return "failed", "F", "failed"
			if report.outcome == "passed":
				return "rerun", "R", "rerun"

def pytest_terminal_summary(terminalreporter):
	""" adapted from
	https://bitbucket.org/hpk42/pytest/src/a5e7a5fa3c7e/_pytest/skipping.py#cl-179
	"""
	tr = terminalreporter
	if not tr.reportchars:
		return

	lines = []
	for char in tr.reportchars:
		if char in "rR":
			show_rerun(terminalreporter, lines)

	if lines:
		tr._tw.sep("=", "rerun test summary info")
		for line in lines:
			tr._tw.line(line)

def show_rerun(terminalreporter, lines):
	rerun = terminalreporter.stats.get("rerun")
	if rerun:
		for rep in rerun:
			pos = rep.nodeid
			lines.append("RERUN %s" % (pos,))
