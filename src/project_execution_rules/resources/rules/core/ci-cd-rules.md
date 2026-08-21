---
paths:
  - ".github/workflows/**/*"
  - ".gitlab-ci.yml"
---

# CI/CD Rules

## WHEN

- `CICD-001`：流水线能力必须以当前配置和实际运行结果为准。

## MUST

- `CICD-002`：本地和 CI 的质量命令应保持一致。
- `CICD-003`：默认流水线不得隐式访问真实外部服务或凭据。

## MUST

- `CICD-004`：修改流水线后必须进行语法验证并记录未能真实运行的部分。

## MUST NOT

部署和环境特有规则只在项目真实具备该能力时启用。
