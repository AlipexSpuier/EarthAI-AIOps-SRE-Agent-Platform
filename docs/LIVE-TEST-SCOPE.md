# Live test scope and records

Every benchmark invocation in this session was finite and explicitly user-authorized. The configured API key was decrypted only in memory by existing application code. It was never printed or written to an artifact. The configured SSH password was likewise used only by the existing Paramiko connection. SSH operations were limited to uptime (plus safe connection information), with host fingerprint validation unchanged.

Reports contain model names, counts, safe metadata, error classes and command exit codes. They do not contain credentials or full server command output. Earlier failed experiments are retained, not erased or folded into later successful samples. Timeouts due to a test's 160/180-second ceiling count as incomplete tests, not model successes. Successful protocol profiles only record a control protocol that has produced real successful read-only tool actions, not a guaranteed availability rating.
