# 1. Base Image: Official lightweight Python 3.10 image
FROM python:3.10-slim

# 2. Set working directory inside container
WORKDIR /function

# 3. Copy dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy scanner source code (main.py)
COPY . .

# 5. Expose Serverless Function Port 8080
EXPOSE 8080

# 6. Command to start functions-framework serverless runtime
CMD ["functions-framework", "--target=scan_document", "--port=8080"]
