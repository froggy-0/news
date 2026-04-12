FROM public.ecr.aws/lambda/python:3.11

# 외부 의존성 없음 — stdlib(urllib, json)만 사용
COPY handler.py ${LAMBDA_TASK_ROOT}

CMD ["handler.lambda_handler"]
