class ClaudeCodeUsageBar < Formula
  desc     "Claude Code usage stats in your macOS menu bar"
  homepage "https://github.com/ronkeee/claude-code-usage-bar"
  url      "https://github.com/ronkeee/claude-code-usage-bar/archive/refs/tags/v1.0.0.tar.gz"
  sha256   "60002d741b51f579d04ef100c06f7f025c70154b13a44099f598c8a0aa538e2f"
  license  "MIT"
  version  "1.0.0"

  depends_on "python@3.12"
  depends_on :macos

  resource "rumps" do
    url "https://files.pythonhosted.org/packages/source/r/rumps/rumps-0.4.0.tar.gz"
    sha256 "17fb33c21b54b1e25db0d71d1d793dc19dc3c0b7d8c79dc6d833d0cffc8b1596"
  end

  resource "pyobjc" do
    url "https://files.pythonhosted.org/packages/source/p/pyobjc/pyobjc-10.3.tar.gz"
    sha256 "4af8a73bf5d73fc62f6cceb8826d6fc86db63017bf75450140a4fa7ec263db6b"
  end

  resource "keyring" do
    url "https://files.pythonhosted.org/packages/source/k/keyring/keyring-25.7.0.tar.gz"
    sha256 "fe01bd85eb3f8fb3dd0405defdeac9a5b4f6f0439edbb3149577f244a2e8245b"
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
