This document is a development document. If you need to deploy the Xiaozhi (小智) server-side, [click here to view the deployment tutorial](../../README.md#deployment-documentation).

To view the deployment of the all-in-one digital human machine, Kiosk full-screen startup, and system environment configuration, [click here to view the All-in-One Machine Deployment Guide](../../docs/all-in-one-digital-human-setup.md).

To view wake word model downloads, runtime configurations, and detailed instructions, [click here to view the Wake Word Special Documentation](../../docs/digital-human-wakeword.md).

# Project Introduction

`digital-human` is an independent digital human testing module. It is responsible for providing local test pages, front-end interaction resources, wake word runtimes, and event bridge capabilities, which are used to jointly debug the entire digital human interaction pipeline.

# Quick Start

Install dependencies:

```bash
pip install -r wakeword_runtime/requirements.txt

启动模块：

```bash
python start.py
```

Access URLs
After startup, you can access:

Page Address: http://127.0.0.1:8006/index.html

Event Bridge Address: ws://127.0.0.1:8006/wakeword-ws

Health Check: http://127.0.0.1:8006/health

Directory Structure
start.py: Module startup entry point

index.html: Digital human test page entry point

wakeword_runtime: Local wake word runtime and configuration directory

js, css: Page front-end scripts and stylesheets

images, resources: Page resource files

Related Documentation
All-in-One Machine Deployment Guide: Applicable to full x86 device deployments, Kiosk displays, and boot-up self-start configurations.

Wake Word Special Documentation: Applicable to wake word model downloads, runtime configurations, and local debugging instructions.
"""

output_filename = "README_EN.md"
with open(output_filename, "w", encoding="utf-8") as f:
f.write(english_readme_content)

print(f"File successfully saved to {output_filename}")
