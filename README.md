# prometheus_notice

## 配置文件

```yaml
email:
  smtp_server: smtp 服务地址
  smtp_port: smtp 服务端口
  from_name: 发送者名称
  username: 发送者邮箱
  password: 发送者邮箱密码
  # 收件人列表
  recipients:
    - example@email.com
prometheus:
  # prometheus 地址
  url: http://localhost:32290/api/v1/query
```

![image-20241111172910159](http://221.6.17.74:47080/i/2024/11/11/slgyhg-0.png)