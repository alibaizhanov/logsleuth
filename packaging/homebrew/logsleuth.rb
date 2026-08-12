class Logsleuth < Formula
  include Language::Python::Virtualenv

  desc "Root-cause analysis that reads the whole log file, locally"
  homepage "https://github.com/alibaizhanov/logsleuth"
  url "https://files.pythonhosted.org/packages/46/c9/5e8d1b088de5af6f83553843c28b44493de4be0ec19fb53dd03a538725bb/logsleuth-0.13.1.tar.gz"
  sha256 "37ee3b0af2852af66a55ef1e8610521d7377ef33c1f7c95c4762a8d0599da044"
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

    # The MCP entry point is a separate console script; a broken one would otherwise
    # ship unnoticed, since nothing else in this test touches it. One initialize
    # round-trip over stdio proves the protocol path works end to end.
    init = '{"jsonrpc":"2.0","id":1,"method":"initialize",' \
           '"params":{"protocolVersion":"2025-06-18","capabilities":{}}}'
    reply = pipe_output(bin/"logsleuth-mcp", "#{init}\n")
    # Match on structure, not on byte-exact JSON: the serializer's spacing is not
    # part of the contract and pinning it makes the test fail on a formatting change
    # that breaks nothing.
    assert_match(/"name":\s*"logsleuth"/, reply)
    assert_match version.to_s, reply
  end
end
