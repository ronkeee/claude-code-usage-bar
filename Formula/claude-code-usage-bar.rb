class ClaudeCodeUsageBar < Formula
  desc     "Claude Code usage stats in your macOS menu bar"
  homepage "https://github.com/ronkeee/claude-code-usage-bar"
  url      "https://github.com/ronkeee/claude-code-usage-bar/archive/refs/tags/v1.0.0.tar.gz"
  sha256   "REPLACE_WITH_SHA256_AFTER_RELEASE"
  license  "MIT"
  version  "1.0.0"

  depends_on "python@3.12"
  depends_on :macos

  resource "rumps" do
    url "https://files.pythonhosted.org/packages/source/r/rumps/rumps-0.4.0.tar.gz"
    sha256 "REPLACE_WITH_SHA256"
  end

  resource "pyobjc" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc/pyobjc-10.3.tar.gz"
    sha256 "REPLACE_WITH_SHA256"
  end

  resource "keyring" do
    url "https://files.pythonhosted.org/packages/source/k/keyring/keyring-25.7.0.tar.gz"
    sha256 "REPLACE_WITH_SHA256"
  end

  def install
    venv = virtualenv_create(libexec, "python3.12")
    venv.pip_install resources
    libexec.install "claude_usage_bar.py"

    # Write a wrapper script so `brew services` can find the right python
    (bin/"claude-code-usage-bar").write <<~EOS
      #!/bin/bash
      exec "#{libexec}/bin/python3" "#{libexec}/claude_usage_bar.py" "$@"
    EOS
  end

  service do
    run        [opt_bin/"claude-code-usage-bar"]
    keep_alive true
    log_path   "/tmp/claude-usage-bar.log"
    error_log_path "/tmp/claude-usage-bar.log"
  end

  def caveats
    <<~EOS
      Claude Code Usage Bar has been installed.

      Start it with:
        brew services start claude-code-usage-bar

      The app icon will appear in your macOS menu bar.

      For live plan limits (optional), click the icon and choose
      "Setup Live Data…" — takes about 2 minutes, never again after that.
    EOS
  end

  test do
    system "#{bin}/claude-code-usage-bar", "--version"
  end
end
