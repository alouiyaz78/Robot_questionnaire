##  Overview

This PR introduces a complete interactive quiz generation system based on course documents, with both CLI and Streamlit UI.

The application allows users to:
- Upload documents (PDF, TXT, DOCX, PY, IPYNB)
- Generate quizzes automatically using AI
- Answer questions interactively
- Get scoring and feedback
- Export results (Markdown / DOCX)

---

##  Features

###  Quiz Generation
- Generate QCM from multiple document formats
- Chunk-based processing for large files
- AI-based question generation

###  Difficulty Levels
- `facile`: basic understanding
- `moyen`: application & reasoning
- `difficile`: comparison & interpretation

###  Question Quality Improvements
- Only autonomous questions (no missing context)
- No duplicate questions (similarity filtering)
- Added comparison-based questions
- Removed open-ended questions

###  Scoring System
- Full scoring for single-answer questions
- Partial scoring for multi-select:
  - +points for correct answers
  - -points for wrong answers
  - no penalty for missing correct answers
  - score bounded between 0 and max points

###  Streamlit UI
- Upload documents directly from UI
- Input API key securely
- Select difficulty level
- Interactive answering system
- Real-time scoring
- Export results

###  Export
- Markdown (QCM + corrigé)
- DOCX (questionnaire + correction)
- JSON (sources, answers)
### Deployment

This application is deployed to production on Hugging Face Spaces via Gradio.

**Try the live app:** [Quiz Generator — Hugging Face Spaces](https://huggingface.co/spaces/alouiyaz78/robot_questionnaire)

The app runs in a Docker container managed by Hugging Face Spaces, using Gradio 5.49.1 on Python 3.12.
It is publicly accessible and automatically updated on every push to the repo.

---

##  Project Structure
src/robot_questionnaire/
├── cli.py
├── qcm.py
├── loaders.py
├── chunker.py
├── io_utils.py
├── exam_formatter.py

app/
├── streamlit_app.py
├── utils_ui.py
