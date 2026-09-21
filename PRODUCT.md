# Visão de Produto — Media Optimizer (PRODUCT.md)

## 🎯 1. Visão e Declaração de Missão

O **Media Optimizer** nasceu para resolver um dos gargalos mais comuns e frustrantes da era digital: o crescimento descontrolado do volume de fotos e vídeos pessoais e a complexidade técnica para compactá-los sem perder qualidade visual e metadados históricos.

Nossa missão é fornecer uma **ferramenta desktop moderna, acessível, segura e de altíssima performance**, que qualquer pessoa — desde o usuário leigo até o fotógrafo profissional — possa executar com **dois cliques**, sem precisar instalar Python, FFmpeg ou ferramentas de terminal.

---

## 🛑 2. O Problema que Resolvemos

1. **Arquivos Gigantescos e Incompatíveis:**
   - Celulares modernos gravam vídeos em 4K/60fps ou 1080p/120fps e salvam fotos em formatos proprietários (HEIC, Apple ProRAW, Sony ARW) que ocupam dezenas de gigabytes e não abrem com facilidade em sistemas legados ou na web.
2. **Exportações do Google Photos Takeout:**
   - Usuários que exportam seus acervos para liberar espaço na nuvem do Google deparam-se com centenas de gigabytes de pastas confusas, fotos com rotação invertida e arquivos pesados.
3. **Complexidade de Ferramentas Existentes:**
   - Ferramentas como FFmpeg puro ou ImageMagick exigem scripts complexos de linha de comando, parametrização detalhada de filtros e instalação manual de binários.
   - Softwares comerciais freemium impõem marcas d'água, limites arbitrários de arquivos ou assinaturas recorrentes.
4. **Instabilidade de Hardware (Thermal Throttling & Crash):**
   - Softwares genéricos disparam centenas de threads descontroladas que consomem 100% da RAM, travam o computador e causam encerramento forçado do sistema operacional (*Out of Memory*).

---

## 👥 3. Personas de Usuários

### Persona 1: O Usuário Doméstico / Familiar
- **Perfil:** Quer apenas liberar espaço no computador ou disco rígido após baixar o Google Takeout ou fotos do iPhone.
- **Necessidade:** Interface visual intuitiva em português, botão de início rápido, sem jargões técnicos complexos e com garantia absoluta de que as fotos originais nunca serão apagadas.

### Persona 2: O Fotógrafo Entusiasta / Criador de Conteúdo
- **Perfil:** Possui acervos em formato RAW (.ARW, .CR2, .NEF, .DNG) e fotos em alta definição.
- **Necessidade:** Conversão em lote rápida, redimensionamento de alta fidelidade (LANCZOS) para publicação online, preservação dos dados EXIF (câmera, lente, ISO, data) e controle de qualidade e concorrência.

### Persona 3: O Usuário Técnico / Sysadmin
- **Perfil:** Quer rodar automações em lote no servidor doméstico ou NAS.
- **Necessidade:** Suporte completo a CLI com flags descritivas, modo simulação (*dry-run*), telemetria via console e saída em formatos portáteis (AppImage, Flatpak).

---

## 💎 4. Proposta de Valor Central

| Diferencial | Media Optimizer | Softwares Convencionais / Scripts Simples |
| :--- | :--- | :--- |
| **Instalação** | Zero dependências (FFmpeg e bibliotecas inclusas) | Requer instalar Python, FFmpeg e dependências no terminal |
| **Segurança** | Originais 100% intocados e escrita atômica (`.tmp`) | Risco de sobrescrever fotos originais |
| **Estabilidade** | Telemetria ativa com Auto-Throttling anti-crash | Congela o computador por saturação de RAM |
| **Aceleração** | Suporte universal: NVIDIA RTX/GTX/GT, AMD Radeon/RX, Intel Arc/Iris, Apple Silicon e CPU x86/x64/ARM | Frequentemente apenas CPU lenta |
| **Custos** | Código aberto, sem anúncios ou assinaturas | Pago ou com limitações de recursos |

---

## 🗺️ 5. Roadmap de Produto

### Fase 1 (Versão Atual - v1.0.0)
- [x] Motor desacoplado com suporte a imagens HEIC, RAW, AVIF, PNG, JPG.
- [x] Otimização inteligente de vídeos com capping de FPS e aceleração universal (NVIDIA NVENC, AMD AMF/VAAPI, Intel QSV, Apple VideoToolbox e CPU libx264).
- [x] Interface gráfica moderna CustomTkinter com temas Claro/Escuro/Sistema.
- [x] Telemetria dinâmica e controle de prioridade no sistema operacional.
- [x] Empacotamento multiplataforma (.exe, AppImage, Flatpak, .dmg).
- [x] Cobertura obrigatória de 100% de testes e automação de releases no GitHub.

### Fase 2 (v1.1.0)
- [ ] Presets de exportação com 1 clique (ex: "Compartilhar no WhatsApp", "Arquivo Frio em Nuvem", "Portfólio Web").
- [ ] Histórico de diretórios recentes e suporte a arrastar-e-soltar (*drag and drop* de pastas na interface).
- [ ] Integração com leitor de datas em arquivos `.json` complementares do Google Takeout.

### Fase 3 (v2.0.0)
- [ ] Detecção e remoção inteligente de fotos duplicadas por hash perceptual (pHash).
- [ ] Suporte a codificação em AV1 por hardware para economia adicional de 30% em vídeo.
- [ ] Internacionalização completa (PT-BR, EN, ES).
