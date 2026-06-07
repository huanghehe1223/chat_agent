效果录屏展示：

1.多轮对话，思考过程展示，流式输出

```txt
视频链接
https://github.com/user-attachments/assets/49875343-2a8f-49e9-813c-dc7fe73b005a
```

视频描述先问了"你知道中国吗"

又问了"它的经济中心在哪里"

思考过程和正式回答都正常渲染，并且能识别出指代词是中国，说明支持多轮对话

2.同一个session，对话记录持久化，刷新后能继续对话

```txt
https://github.com/user-attachments/assets/80d4e15b-b809-433c-8564-16a803ed8100
```

刷新页面，对话记录仍然加载出来，在之前对话的基础上，接着询问"它有多少个民族"

仍然能正确回应，对话记录持久化

具体的对话记录可以查看data/sessions/简单测试.json

具体请求响应详情可以查看data/sessions/简单测试.req_res.log

2.5多session管理，各session独立

```txt
https://github.com/user-attachments/assets/28f73a59-a8a3-4476-970a-b347e1adf96d
```

视频描述：切换不同的session，每个session都有自己的对话记录，都正常渲染展示

3.工具调用示例，search，calculator，显示tool_use和tool_result信息

北京最近天气怎么样，模型给出search的tool_use响应，系统自动给出tool_result结果，这两部分内容也正确渲染

```txt
https://github.com/user-attachments/assets/c9a45478-f1fd-4235-b8b8-a57b54afc944
```

计算一下889*(554-3)，模型给出search的tool_use响应

```txt
https://github.com/user-attachments/assets/dd4ab8db-a268-417c-a0d8-1d423eef1904
```

具体的对话记录可以查看data/sessions/简单工具调用.json

具体请求响应详情可以查看data/sessions/data/sessions/简单工具调用.req_res.log

4.task list功能展示

先输入"创建一个任务列表，先搜索什么是RAG，再搜索有哪些RAG框架，最后搜索最新RAG前沿技术，只完成第一个任务即可"

模型调用manage_todo_list生成对应的task列表，并且只要任务更新，就会调用manage_todo_list工具进行task礼包更新，task列表是session级别的持久化，session页面会实时更新task状态（左侧）

接着刷新，task状态仍然保留

再输入"现在完成第二个任务"，模型调用相关工具完成任务，并且调用manage_todo_list，更新任务状态，session渲染ui也实时更新第二个任务的状态，未开始-->进行中-->完成

构建任务列表，进行session级持久化，实时追踪

```txt
https://github.com/user-attachments/assets/dc918742-fd45-42e6-8a1f-1cfb810f95d4
```

具体的对话记录可以查看data/sessions/持久化任务.json

具体请求响应详情可以查看data/sessions/持久化任务.req_res.log



创建一个任务列表，先搜索什么是RAG，再搜索有哪些RAG框架，最后搜索最新RAG前沿技术，只完成第一个任务即可



现在完成第二个任务

5.工具调用日志详情

web页面能查看每个session的具体工具调用日志

查看工具名称，参数，调用结果

```txt
https://github.com/user-attachments/assets/7c791baf-1398-493e-be13-70c73939c444
```