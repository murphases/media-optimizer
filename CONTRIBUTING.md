# Guia de Contribuição — Media Optimizer

Obrigado pelo seu interesse em contribuir para o **Media Optimizer**! Este projeto é de código aberto e comunitário sob a licença **PolyForm Noncommercial 1.0.0** (uso estritamente não-comercial).

---

## 🎯 Princípios Fundamentais do Projeto

1. **Segurança Inegociável de Dados:** Os arquivos originais do usuário são sagrados. Nenhuma etapa ou linha de código deve apagar, substituir in-place ou mover os arquivos de origem. A escrita de saída é sempre atômica (`.tmp` -> renomeação após validação).
2. **Zero Dependências para o Usuário Final:** O usuário que baixa o `.exe`, `.AppImage` ou `.dmg` não deve precisar instalar Python, FFmpeg ou bibliotecas adicionais.
3. **Qualidade e Cobertura Total:** O repositório impõe um **Gate Obrigatório de 100% de Cobertura de Testes** para a lógica central no pipeline de CI. Qualquer PR com falhas ou cobertura < 100% será bloqueado.

---

## 🛠️ Ambiente de Desenvolvimento

### 1. Clonar o repositório
```bash
git clone https://github.com/murphases/media-optimizer.git
cd media-optimizer
```

### 2. Criar e ativar ambiente virtual
```bash
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate
```

### 3. Instalar dependências em modo editável
```bash
pip install -r requirements.txt
pip install -e .
pip install pytest pytest-cov pytest-mock pyinstaller ruff
```

---

## 🧪 Como Rodar os Testes

Execute a suíte completa com medição de cobertura:
```bash
pytest --cov=media_optimizer --cov-report=term-missing --cov-fail-under=100
```

Para rodar testes específicos:
```bash
pytest tests/test_converter.py -v
```

---

## 🔀 Fluxo de Trabalho Git (Branch e Pull Request)

1. Faça um Fork do repositório.
2. Crie uma branch para sua funcionalidade ou correção:
   ```bash
   git checkout -b feature/minha-melhoria
   ```
3. Escreva código limpo, seguindo PEP 8 e adicionando docstrings informativas.
4. Adicione testes cobrindo todas as novas linhas e ramificações (branches).
5. Certifique-se de que os testes passam localmente com 100% de cobertura.
6. Envie o commit com mensagem semântica:
   - `feat: adiciona suporte a perfil AVIF para web`
   - `fix: corrige verificação de codec em mídias verticais`
   - `docs: adiciona instruções de empacotamento no Linux`
7. Abra o Pull Request preenchendo o template oficial.

---

## 🛡️ Código de Conduta
Ao participar deste projeto, você concorda em cumprir os padrões estabelecidos em nosso [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
