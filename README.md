# 豆瓣记录导出

将豆瓣用户的电影（已看/想看）和图书（已读/想读）列表分别导出为 CSV 和 Markdown。

## 用法

```bash
python douban_movie_export.py <用户名> [--cookie "cookie字符串"] [--type movie|book|all]
```

| 参数 | 说明 |
|------|------|
| `<用户名>` | 豆瓣用户 ID（URL 中 `/people/` 后面的部分） |
| `--cookie` | 可选，浏览器 Cookie 字符串，绕过访问限制 |
| `--type` | `movie`=仅电影, `book`=仅图书, `all`=全部（默认） |

## 示例

```bash
# 导出全部（电影 + 图书）
python douban_movie_export.py 249536212

# 仅导出图书
python douban_movie_export.py 249536212 --type book

# 仅导出电影，带 Cookie
python douban_movie_export.py 249536212 --type movie --cookie "ll=\"xxx\""
```

## 输出

| 文件 | 内容 |
|------|------|
| `{用户名}_movies.csv / .md` | 已看电影 |
| `{用户名}_movie_wish.csv / .md` | 想看电影 |
| `{用户名}_books.csv / .md` | 已读图书 |
| `{用户名}_book_wish.csv / .md` | 想读图书 |

### 导出字段

名称 / 评分 / 日期 / 简介（作者·译者·出版年） / 短评 / 封面 / 豆瓣链接

## 安装依赖

```bash
pip install -r requirements.txt
```

- `requests`
- `beautifulsoup4`

## Cookie 获取方法

1. 浏览器打开豆瓣并登录
2. F12 → Network → 刷新页面 → 点击任意请求
3. 复制 Request Headers 中的 `Cookie` 值

## 注意事项

- 未提供 Cookie 时只能抓取公开数据，可能遇到 403
- 每页间隔 2-4 秒随机延迟，避免被封
- 自动按链接去重，不会输出重复条目
