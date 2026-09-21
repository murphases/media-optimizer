# 📸 Otimizador Inteligente de Fotos e Vídeos (Google Photos Takeout)

Aplicativo profissional com **Interface Gráfica Moderna (Dark Theme)** e monitoramento inteligente de hardware em tempo real (**Intel Core i7-13650HX** + **32GB RAM** + **NVIDIA RTX 4050 6GB**), projetado para converter e otimizar acervos de fotos e vídeos com **segurança absoluta dos dados originais** e proteção contra sobrecarga de hardware.

---

## ⚡ Como Iniciar o Aplicativo

### Opção 1: Dois Cliques no Windows (Mais Fácil)
Dê um duplo clique no arquivo:
👉 **`iniciar_aplicativo.bat`**

---

### Opção 2: Pelo Terminal
```powershell
python app_otimizador_midia.py
```

---

## 🖥️ Funcionalidades da Interface Gráfica

### 1. 🛡️ Painel de Telemetria de Hardware em Tempo Real (Anti-Crash)
- **CPU (i7-13650HX):** Monitoramento contínuo da carga de trabalho com prioridade do Windows ajustada para `BELOW_NORMAL_PRIORITY_CLASS`.
- **Memória RAM (32GB):** Medidor em GB e porcentagem com **Auto-Throttling**: se o consumo ultrapassar 88%, o motor desacelera o despacho para evitar falta de memória (*Out Of Memory*).
- **GPU & VRAM (RTX 4050):** Medição de VRAM usada (6GB) e temperatura da GPU em tempo real.
- **Botões de Controle Dinâmico:** `▶️ Iniciar`, `⏸️ Pausar`, `▶️ Retomar` e `⏹️ Cancelar` a qualquer momento.

---

### 2. 🗂️ Abas de Operação

#### 🟢 Aba 1: Converter Imagens para JPG
- Converte todas as imagens (.HEIC, .HEIF, .PNG, .WEBP, .AVIF, .ARW Sony RAW, .JPEG) para `.jpg` em `Convertidos\JPG`.
- Seleção visual de pasta de origem e destino via botão *Procurar...*.
- Slider de qualidade JPG inicial (padrão: 95%).
- Slider de processos paralelos (*workers*, padrão: 8).

#### 🔵 Aba 2: Otimizar Imagens JPG (70%)
- Otimiza as fotos para JPG com 70% de qualidade e reduz o lado maior para **no máximo 1350px** (sem upscale em imagens menores).
- Preserva rigorosamente proporções e orientação EXIF.
- Salva em `Otimizadas\JPG`.
- Cálculo e exibição em tempo real do espaço economizado em disco (GB e %).

#### 🟣 Aba 3: Otimizar Vídeos (.MOV)
- Otimiza todos os vídeos para formato `.mov` com resolução máxima de 1920px no lado maior.
- **Ajuste inteligente de FPS:** se o vídeo original tiver mais de 30 fps, reduz para 30 fps; se tiver $\le$ 30 fps, mantém o original (ex: 24 fps).
- **Aceleração por Hardware:** Codificação ultrarrápida via **NVIDIA NVENC (RTX 4050)** com fallback automático para CPU (`libx264`).

#### 🚀 Aba 4: Pipeline Completo
- Executa em lote automatizado as etapas 1 $\rightarrow$ 2 $\rightarrow$ 3 com apenas um clique.

---

## 🔒 Garantias de Segurança

- **Arquivos Originais Intactos:** A pasta `Originais` é estritamente **somente leitura**. Nenhum arquivo original será excluído, movido ou alterado.
- **Escrita Atômica:** Cada arquivo é gerado inicialmente como `.tmp` e só é renomeado após verificação de sucesso.
- **Logs e Tratamento de Erros:** Erros em arquivos individuais com cabeçalho corrompido são registrados em `logs/` e a fila continua sem interrupções.
- **Modo Simulação (Dry-Run):** Checkbox na interface permite simular todo o processo sem gravar arquivos.
- **Capacidade de Retomada (*Resume*):** Se o processo for pausado ou fechado, ao reiniciar ele pula automaticamente os arquivos já finalizados.
