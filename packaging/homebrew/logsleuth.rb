class Logsleuth < Formula
  include Language::Python::Virtualenv

  desc "Root-cause analysis that reads the whole log file, locally"
  homepage "https://github.com/alibaizhanov/logsleuth"
  url "https://files.pythonhosted.org/packages/15/a2/773b8c062c12dbb0aa7f6f53454ca4e4d28a3d129d55c0df4e0d270ab492/logsleuth-0.11.0.tar.gz"
  sha256 "1f5de55232e52433e9474c64095b0fc7659a3864cf3b03668f509149e79f33fc"
  license "MIT"

  depends_on "python@3.13"

  # No resource blocks: logsleuth is pure standard library and declares no
  # dependencies, so the virtualenv contains exactly one package.
  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      logsleuth runs its model locally, so nothing you analyze leaves this machine.
      On first use it offers to download a runtime and a model (~5GB) into
      ~/.logsleuth; if you already run Ollama it uses that and downloads nothing.

      Try it on a bundled sample incident:
        logsleuth demo

      To see exactly what would be sent to the model, and nowhere else:
        logsleuth <your.log> --dry-run
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/logsleuth --version")

    # Exercise the real work — scan, template mining, rare-event ranking, trend
    # extraction — without contacting a model or the network. --dry-run prints the
    # evidence pack and exits, so this stays hermetic, which a formula test must be.
    (testpath/"incident.log").write <<~EOS
      2026-08-04T12:00:00.100Z INFO  api handled /v1/orders status=200 latency=21ms
      2026-08-04T12:00:01.200Z INFO  api handled /v1/orders status=200 latency=24ms
      2026-08-04T12:00:02.300Z INFO  api handled /v1/users status=200 latency=19ms
      2026-08-04T12:00:03.400Z INFO  config applied: DB_POOL_MAX=4 (was 40) by deploy
      2026-08-04T12:00:04.500Z ERROR api db pool timeout after 2000ms acquiring connection
      2026-08-04T12:00:05.600Z ERROR api db pool timeout after 2000ms acquiring connection
      2026-08-04T12:00:06.700Z ERROR api db pool timeout after 2000ms acquiring connection
      2026-08-04T12:00:07.800Z ERROR api db pool timeout after 2000ms acquiring connection
    EOS

    pack = shell_output("#{bin}/logsleuth #{testpath}/incident.log --dry-run")
    assert_match "RARE / NOTABLE EVENTS", pack
    assert_match "DB_POOL_MAX", pack

    # Diagnostics mode must never echo log content — that is the property which
    # makes it safe to paste into a bug report.
    health = shell_output("#{bin}/logsleuth #{testpath}/incident.log --health")
    refute_match "DB_POOL_MAX", health
  end
end
