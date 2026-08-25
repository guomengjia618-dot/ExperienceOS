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
