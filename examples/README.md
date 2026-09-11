# 示例

[`experience.example.json`](experience.example.json) 是一份完整的 Experience
记录示例（毕业设计类型），可作为手工建档的模板。

导入到你的库（重新生成 id，不影响已有记录）：

```bash
python -c "
import json
from pathlib import Path
from experienceos.core.models import Experience, new_ulid
from experienceos.storage import ExperienceStore
from experienceos.config import resolve_home
data = json.loads(Path('examples/experience.example.json').read_text(encoding='utf-8'))
data['id'] = 'exp_' + new_ulid()
ExperienceStore(resolve_home()).save(Experience.from_dict(data))
print('saved', data['id'])
"
```

> 示例中的 id 与时间戳是演示值；真实记录的 id 由 `experienceos add`
> 自动生成。

## Agent Demo

无需 API Key 的完整闭环（录制模型回复，但 3 个工具、存储读取、检查点、
Schema 校验和证据护栏都走真实生产代码）：

    python examples/agent_demo.py

使用 config.toml 中配置的真实模型 API：

    set OPENAI_API_KEY=your-key
    python examples/agent_demo.py --live

默认是 `openai-compat`；把 config.toml 的 `ai.provider` 改为
`openai-responses` 可走 Responses API。每次成功运行都会在 demo home 的
`reports/` 下保存不含问题、回答和 Tool 结果的脱敏指标报告。

若网络或模型调用中断，错误中会打印 workflow ID；修复问题后续跑：

    python examples/agent_demo.py --live --resume wf_...
