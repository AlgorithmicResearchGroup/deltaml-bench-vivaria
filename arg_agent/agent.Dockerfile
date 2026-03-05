ARG TASK_IMAGE=us-central1-docker.pkg.dev/vivaria/task-environments/ai_rd_triton_cumsum
FROM ${TASK_IMAGE}

# Switch to agent user for package installation
USER agent
WORKDIR /home/agent

# Add .local/bin to PATH to fix pip warnings
ENV PATH="/home/agent/.local/bin:$PATH"

# Copy requirements and install packages with smart conflict resolution
COPY requirements.txt .
RUN --mount=type=cache,target=/home/agent/.cache \
    python -m pip install --user -r requirements.txt --upgrade-strategy only-if-needed

# Copy agent code
COPY . .

# Keep the agent user for execution
USER agent

# Run the agent
ENTRYPOINT ["python", "main.py"]
