# Lambda image for the custom strategies. Build context is custom/, so
# nothing in the OpenAlgo tree goes into it:
#   docker build -f custom/lambda/Dockerfile custom
FROM public.ecr.aws/lambda/python:3.12

COPY lambda/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY nse_utils.py lambda/lambda_handler.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_handler.handler"]
