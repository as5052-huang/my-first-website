# AI 简历一键优化

基于 Streamlit + DeepSeek 的本地简历优化工具：针对目标岗位润色简历、提炼亮点、清理空话，并给出 ATS 建议与扣分整改方案。

## 环境

- Python 3.10+
- [DeepSeek API Key](https://platform.deepseek.com/)

## 运行

```bash
cd resume-optimizer
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # macOS/Linux 使用 cp .env.example .env
```

在 `.env` 中填写：

```
DEEPSEEK_API_KEY=sk-你的密钥
```

启动：

```bash
streamlit run app.py
```

浏览器打开提示的本地地址即可。也可不写 `.env`，在页面左侧栏临时填入 API Key。

## 功能

1. 粘贴简历，或上传 PDF / DOCX / TXT  
2. 填写岗位名称，可选粘贴 JD  
3. 生成优化正文、工作亮点、岗位匹配说明  
4. ATS 建议 + 扣分点整改  
5. 一键复制、导出 TXT  

扫描件 PDF 无法抽字时，请改用可选中文字的文件，或直接粘贴文本。
