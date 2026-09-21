# AGENTS.md — Instruções para Agentes de Inteligência Artificial

Este documento define a arquitetura, regras operacionais, invariantes de integridade e padrões de engenharia para qualquer agente de IA autônomo ou assistente de programação que opere neste repositório.

---

## 🧭 Visão Geral do Repositório

O **Media Optimizer** é um aplicativo de processamento de mídia de alta performance focado em converter e compactar grandes coleções de imagens e vídeos (como Google Photos Takeout, cartões SD de câmeras e backups de smartphones) mantendo máxima fidelidade visual e integridade total dos arquivos.

### Estrutura de Diretórios
```text
├── media_optimizer/            # Pacote central de lógica e interface
│   ├── __init__.py             # Versão, metadados e exports públicos
│   ├── config.py               # Persistência de configurações e presets (JSON)
│   ├── hardware.py             # Telemetria dinâmica multiplataforma e auto-throttling
│   ├── ffmpeg_tools.py         # Resolução autônoma de binários, probing e builders de comando
│   ├── converter.py            # Motor de conversão de imagens (HEIC, RAW, AVIF, PNG -> JPG)
│   ├── image_optimizer.py      # Motor de compressão/redimensionamento LANCZOS sem upscale
│   ├── video_optimizer.py      # Motor de compressão de vídeos (NVENC, VideoToolbox, CPU)
│   ├── pipeline.py             # Orquestrador unificado, controle de pausa/cancelamento e métricas
│   ├── cli.py                  # Interface de linha de comando
│   └── gui.py                  # Interface gráfica moderna CustomTkinter
├── packaging/                  # Especificações de empacotamento multiplataforma
│   ├── windows/                # PyInstaller .spec e Inno Setup .iss
│   ├── linux/                  # AppRun, desktop entry e build_appimage.sh
│   ├── flatpak/                # Manifesto Flatpak
│   └── macos/                  # Script build_dmg.sh
├── scripts/                    # Scripts de suporte e automação (ex: bundle_ffmpeg.py)
├── tests/                      # Suíte de testes com cobertura total (100%)
├── .github/                    # Workflows de CI/CD (ci.yml, release.yml) e templates
├── main.py                     # Ponto de entrada padrão
└── app_otimizador_midia.py     # Ponto de entrada retrocompatível
```

---

## 🔒 Invariantes Rígidos de Segurança (Não Negociáveis)

Qualquer alteração sugerida por agentes de IA DEVE respeitar impreterivelmente as seguintes garantias:

1. **Imutabilidade Estrita da Origem:**
   - A pasta de entrada (`input_dir`) é estritamente **somente leitura**.
   - NUNCA execute operações de escrita, exclusão ou renomeação no diretório de origem.
2. **Escrita Atômica em Disco:**
   - Todo arquivo processado deve ser gerado inicialmente com a extensão temporária `.tmp` (ou `.tmp.ext`).
   - Somente após validação completa da escrita, fechamento dos descritores de arquivo e aplicação dos timestamps (`os.utime`), o arquivo temporário é renomeado para o destino definitivo.
3. **Resiliência a Falhas de Mídia:**
   - Erros em arquivos corrompidos ou não reconhecidos NUNCA devem derrubar o processo em lote. Registre o erro no log e continue a fila.
4. **Sem Upscale:**
   - Se uma imagem ou vídeo tiver dimensões menores que o teto configurado (ex: 1350px ou 1920px), sua resolução original deve ser estritamente preservada.
5. **Zero Dependências no Usuário Final:**
   - NUNCA assuma que o usuário final possui Python ou FFmpeg instalado no PATH. Utilize sempre o `FFmpegResolver`.
6. **Portabilidade Multiplataforma:**
   - NUNCA assuma hardware específico (ex: não fixe nomes de processadores ou placas NVIDIA no código). Use `HardwareMonitor` para detecção dinâmica e fallback suave.

---

## 🧪 Padrão de Testes e Cobertura (100%)

- O repositório possui uma regra bloqueante no CI de **100% de cobertura de código**.
- Ao criar novos métodos ou funções, você DEVE escrever testes unitários cobrindo:
  - O caminho de sucesso (*happy path*).
  - Condições de erro e exceções.
  - Modo simulação (*dry-run*).
  - Casos de cancelamento ou pausa.
  - Arquivos já existentes (*resume*).

### Como rodar os testes
```bash
pytest --cov=media_optimizer --cov-report=term-missing --cov-fail-under=100
```

---

## 📝 Convenções de Código

- **Tipagem Estática:** Use `typing` / type annotations em todas as assinaturas de funções e métodos (`from __future__ import annotations`).
- **Docstrings:** Documente classes e funções públicas em formato conciso e claro.
- **Tratamento de Exceções:** Capture erros específicos ou limpe arquivos temporários em blocos `finally` caso ocorra uma falha.
- **Licenciamento:** Todo código novo faz parte do projeto sob a licença **PolyForm Noncommercial 1.0.0**.
