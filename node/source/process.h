#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cstdlib>
#include <utility>
#include <cstdarg>

#include <fmt/format.h>

class process
{
public:
	static constexpr pid_t INVALID_PID = -1;
	static constexpr auto env = "/usr/bin/env";

	struct process_arg
	{
		const char *program_name;
		const char **argv;
		const char *cwd;
	};

	inline
	process(const char *program_name, const char **argv, const char *cwd = nullptr) noexcept
	{
		struct process_info proc = create_process(program_name, argv, cwd);

		this->m_pid = proc.pid;
		this->m_stdin = proc.stdin;
		this->m_stdout = proc.stdout;
		this->m_stderr = proc.stderr;
	}

	process(const process &other) = delete;

	inline
	process(process &&other) noexcept
	: m_pid(other.m_pid)
	, m_stdin(other.m_stdin)
	, m_stdout(other.m_stdout)
	, m_stderr(other.m_stderr)
	{
		other.m_pid = INVALID_PID;
	}

	process& operator=(const process &other) = delete;

	inline
	process& operator=(process &&other) noexcept
	{
		pid_t pid = other.m_pid;
		
		other.m_pid = INVALID_PID;

		this->m_pid = pid;
		this->m_stdin = other.m_stdin;
		this->m_stdout = other.m_stdout;
		this->m_stderr = other.m_stderr;

		return *this;
	}

	inline process& operator=(process_arg pa) noexcept
	{
		this->close_checked();

		struct process_info proc = create_process(pa.program_name, pa.argv, pa.cwd);

		this->m_pid = proc.pid;
		this->m_stdin = proc.stdin;
		this->m_stdout = proc.stdout;
		this->m_stderr = proc.stderr;

		return *this;
	}

	inline void close_() noexcept
	{
		this->m_pid = INVALID_PID;
		close(this->m_stdin);
		close(this->m_stdout);
		close(this->m_stderr);
	}

	inline
	void close_checked() noexcept
	{
		if (this->m_pid == INVALID_PID)
			return;

		this->close_();
	}

	inline ~process()
	{
		this->close_checked();
	}

	inline ssize_t write(const void *buf, size_t count) noexcept
	{
		return ::write(this->m_stdin, buf, count);
	}

	inline
	ssize_t read(void *buf, size_t count) noexcept
	{
		return ::read(this->m_stdout, buf, count);
	}

	inline
	ssize_t readerr(void *buf, size_t count) noexcept
	{
		return ::read(this->m_stderr, buf, count);
	}

	inline auto
	waitpid(int* errc, int flags = 0) noexcept
	{
		return ::waitpid(this->m_pid, errc, flags);
	}

	inline std::pair<pid_t, int>
	waitpid(int flags = 0) noexcept
	{
		int errc;
		return {::waitpid(this->m_pid, &errc, flags), errc};
	}

	inline auto
	pid() noexcept
	{return this->m_pid;}

	inline auto
	stdin() noexcept
	{return this->m_stdin;}

	inline auto
	stdout() noexcept
	{return this->m_stdout;}

	inline auto
	stderr() noexcept
	{return this->m_stderr;}

private:
	struct process_info
	{
		pid_t pid;
		long stdin, stdout, stderr;

		process_info() noexcept
		: pid(INVALID_PID) {}
	};

	static inline struct process_info
	create_process(const char *program_name, const char **argv, const char *cwd) noexcept
	{
		auto cwd_ = cwd ? cwd : "./";
		fmt::print("Creating new process: {} at {} argv:", program_name, cwd_);
		for (auto arg = argv; *arg != nullptr; ++arg) {
			fmt::print("{} ", *arg);
		}
		putchar('\n');

		struct process_info p;
		int new_stdin[2], new_stdout[2], new_stderr[2];

		if(pipe(new_stdin))
			goto bad_pipe_stdin;

		if(pipe(new_stdout))
			goto bad_pipe_stdout;

		if(pipe(new_stderr))
			goto bad_pipe_stderr;

		p.stdin = new_stdin[1];
		p.stdout = new_stdout[0];
		p.stderr = new_stderr[0];

		p.pid = fork();

		if (p.pid == 0) {
			if (cwd && chdir(cwd))
				exit(1);

			dup2(new_stdin[0], STDIN_FILENO);
			close(new_stdin[1]);

			dup2(new_stdout[1], STDOUT_FILENO);
			close(new_stdout[0]);

			dup2(new_stderr[1], STDERR_FILENO);
			close(new_stderr[0]);

			execv(program_name, (char *const *) argv);
			exit(-1);
		}

		close(new_stdin[0]);
		close(new_stdout[1]);
		close(new_stderr[1]);

		return p;

	bad_pipe_stderr:
		close(new_stdout[0]);
		close(new_stdout[1]);
	bad_pipe_stdout:
		close(new_stdin[0]);
		close(new_stdin[1]);
	bad_pipe_stdin:

		return {};
	}

private:
	pid_t m_pid;
	long m_stdin, m_stdout, m_stderr;
};
