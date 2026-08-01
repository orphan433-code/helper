on run
	try
		set appPOSIX to POSIX path of (path to me)
		if appPOSIX ends with "/" then
			set appPOSIX to text 1 thru -2 of appPOSIX
		end if
		set projectPOSIX to do shell script "dirname " & quoted form of appPOSIX
		set projectDir to projectPOSIX & "/TJSBOT"
		set pythonBin to projectPOSIX & "/.venv/bin/python"
		set checkPy to "test -x " & quoted form of pythonBin
		do shell script checkPy
		set cmd to "cd " & quoted form of projectDir & " && exec " & quoted form of pythonBin & " app_gui.py"
		do shell script cmd
	on error errMsg number errNum
		display alert "TJSBOT — ошибка запуска" message errMsg & return & return & "(код " & errNum & ")" as critical
	end try
end run
