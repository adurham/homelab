# Continue.dev Setup Guide: Local + Cloud AI Hybrid

A comprehensive guide to setting up a hybrid local and cloud AI development environment using Continue.dev, LM Studio, and Docker. This setup optimizes for cost savings (90% local, 10% cloud) while maintaining high performance and capabilities for software development.

## 🎯 What You'll Get

This configuration provides you with:

- **Local AI First**: LM Studio running on your M4 MacBook Pro for 90%+ of tasks (free, fast, private, runs completely offline)
- **Cloud AI Fallback**: Seamless access to OpenAI GPT-4o and Anthropic Claude 3.5 Sonnet for complex problems when needed
- **Autonomous AI Agent**: Full-featured agent that can analyze codebases, generate code, debug issues, execute terminal commands, and refactor across multiple files
- **Advanced Custom Commands**: Specialized prompts optimized for different task types (cursor-agent, cloud-architect, analyze-codebase, find-docs)
- **Cost Optimized**: <$10-20/month by using local models for most work, with intelligent escalation to cloud only when necessary
- **MCP Server Integration**: Docker MCP gateway providing Brave Search, Context7 documentation lookup, Fetch for URLs, Memory for persistence, and Sequential Thinking for advanced reasoning
- **Rich Context Providers**: Access to file, code, diff, terminal, tree, open, currentFile, problems, debugger, repo-map, and OS providers for comprehensive code understanding

## 🚀 Quick Setup

### 1. Download Models in LM Studio

Open LM Studio and download these models:

**Required (at least one)**:
- **qwen/qwen3-coder-30b** - Latest Qwen3 version, excellent for coding tasks, fits in 36GB RAM
- **qwen/qwen2.5-coder-32b** - Proven fallback option, also excellent

**Recommended**:
- **mlx-community/deepseek-coder-33b-instruct-hf-4bit-mlx** - 33B model in 4bit, optimized for Apple Silicon
- **openai/gpt-oss-20b** - Alternative OpenAI-style model

**How to download**:
1. Open LM Studio
2. Click "Search" tab
3. Search for model names above (exact names from config)
4. Click "Download" for each model you want

### 2. Start LM Studio Server

**Enable the server**:
1. In LM Studio, click "Local Server" tab on left
2. Click "Start Server" button
3. Load one of your downloaded models
4. Server runs on port 1234 (default) - must use `/v1` endpoint

**Important**: LM Studio uses OpenAI-compatible API at `http://localhost:1234/v1`

Keep LM Studio running while coding - it provides the local AI models.

### 3. Set Up API Keys (Optional - for Cloud Models)

**Create** `~/.continue/.env`:
```bash
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
VOYAGE_API_KEY=your_key_here
```

**Get API keys**:
- Anthropic: https://console.anthropic.com/
- OpenAI: https://platform.openai.com/api-keys
- Voyage: https://www.voyageai.com/ (for reranker)

**Set usage limits** in their dashboards (recommended: $20/month each)

> **Note**: Cloud models are optional. You can use local models exclusively if you prefer.

### 4. Copy Configuration to Continue.dev

**Copy the config**:
```bash
cp "misc scripts/continue-dev/continue-config.yaml" ~/.continue/config.yaml
```

**Or manually** in VSCode:
1. Open Continue.dev settings (Cmd+Shift+P → "Continue: Open Settings")
2. Copy contents of `continue-config.yaml` from this directory
3. Replace the contents of your Continue.dev config file

### 5. Start MCP Servers (Docker)

**Make sure Docker Desktop is running**, then:
1. Continue.dev will automatically connect to the MCP Docker gateway
2. Available MCP servers include: Brave search, Context7, Fetch, Memory, Sequential Thinking
3. These are configured automatically via Docker MCP gateway

**Tip**: You can auto-allow MCP tools in Continue.dev settings for better UX.

### 6. Restart VSCode

Restart VSCode to load the new configuration.

## 🤖 Available AI Models

### Local Models (Free - Use These First!)

Local models run entirely on your machine using LM Studio, providing fast, private, and free AI assistance.

**Qwen3-Coder-30B [LOCAL]**
- **Description**: Latest Qwen3 version, primary model for all coding tasks
- **Strengths**: Excellent code generation, understanding, and reasoning
- **Performance**: Fast on M4 with 36GB RAM (typically 15-30 tokens/second)
- **Best For**: Code generation, refactoring, debugging, explanations, all general coding tasks
- **Model ID**: `qwen/qwen3-coder-30b`
- **Size**: 30B parameters, ~20GB RAM usage
- **Quantization**: Not quantized (full precision for best quality)

**Qwen2.5-Coder-32B [LOCAL]**
- **Description**: Proven, stable Qwen2.5 version with excellent coding capabilities
- **Strengths**: Very reliable, consistent outputs, well-tested
- **Performance**: Similar to Qwen3, excellent on Apple Silicon
- **Best For**: Tab completion, quick fixes, general coding, as primary fallback
- **Model ID**: `qwen/qwen2.5-coder-32b`
- **Size**: 32B parameters, ~22GB RAM usage
- **Quantization**: Not quantized

**DeepSeek-Coder-33B 4bit [LOCAL]**
- **Description**: Large 33B model quantized to 4-bit for efficiency
- **Strengths**: Strong code analysis, debugging capabilities, optimized for Apple Silicon (MLX)
- **Performance**: Fast inference due to quantization, lower memory usage
- **Best For**: Code analysis, debugging, understanding complex code, code reviews
- **Model ID**: `mlx-community/deepseek-coder-33b-instruct-hf-4bit-mlx`
- **Size**: 33B parameters, ~9GB RAM usage (4-bit quantized)
- **Quantization**: 4-bit (efficient but slightly lower quality than full precision)

**GPT-OSS 20B [LOCAL]**
- **Description**: OpenAI-style alternative model, open source
- **Strengths**: Good general capabilities, different style than Qwen models
- **Performance**: Faster than larger models, good for quick tasks
- **Best For**: General coding tasks, alternative perspective when Qwen models struggle
- **Model ID**: `openai/gpt-oss-20b`
- **Size**: 20B parameters, ~13GB RAM usage
- **Quantization**: Not quantized

### Cloud Models (Paid - Use When Needed)

**Claude 3.5 Sonnet [CLOUD]**
- Best for complex architectural decisions
- Excellent reasoning ability
- **Use for**: Complex refactoring, system design, security audits

**GPT-4o [CLOUD]**
- Strong all-around model
- Great for multi-step problem solving
- **Use for**: Advanced debugging, novel algorithms, complex patterns

### Voyage Reranker (For Better Search)

**Voyage Reranker**
- Improves relevance of @codebase and @docs searches
- Makes codebase analysis more accurate
- **Required for**: Better codebase understanding

## 🎮 Smart Custom Commands

### Primary Commands

**`cursor-agent`** ⭐ **START HERE**
- Autonomous agent that recommends the best model for your task
- Analyzes complexity and guides you to the right model
- Can handle any coding task
- **Default to local models** for cost savings

**`cloud-architect`** 💰 **USE SPARINGLY**
- Explicitly uses cloud AI (Claude or GPT-4)
- For complex problems that local models struggle with
- Only use when local models aren't sufficient

**`analyze-codebase`** 📊
- Analyzes specific components against the project's architecture
- Works with `/init` command to use `.continue/rules/CONTINUE.md`
- Checks alignment with coding standards and patterns
- Suggests improvements for better architecture compliance

### Context Providers Available

Context providers give the AI access to different parts of your development environment. Your config includes these providers:

**Code and Files:**
- **`file`** - Reference specific files by path
- **`code`** - Search across your entire codebase for relevant code
- **`currentFile`** - Reference the currently active file you're editing
- **`open`** - Access all currently open files in your editor

**Project Structure:**
- **`tree`** - Display and navigate directory structures without opening files
- **`repo-map`** - High-level view of your repository structure and relationships

**Development Context:**
- **`diff`** - See changes made to files (git diffs, changes)
- **`terminal`** - Access terminal output and execute commands
- **`problems`** - See compiler errors, linter warnings, and other editor diagnostics
- **`debugger`** - Access debugger state and stack traces when debugging

**System Context:**
- **`os`** - Access operating system information and capabilities

**Usage Examples:**
```
@file:src/main.py - Explain this file
@code:authentication - Show me authentication code
@tree ansible/ - Show directory structure
@diff - What changed in this commit?
@currentFile - Improve this code
@open - How do these open files relate?
```

### Documentation

**`@docs`** - Continue.dev documentation is configured and searchable via context.

## 💡 Usage Strategy

### Default Workflow (90% of time)

1. **Start with local models** - Click Continue chat, local model is selected by default
2. **Ask questions or give commands** - Use Continue chat or custom commands like `/cursor-agent`
3. **Trust local AI** - It handles most coding tasks excellently
4. **Try different local models** - If one doesn't help, switch to another
5. **Use context providers** - Reference files with `@code`, `@file`, `@tree`, etc.

### When to Use Cloud AI (10% of time)

Switch to Claude or GPT-4 when:
- Local model gives poor results after trying 2-3 local models
- You need latest security threat knowledge
- Working on novel algorithms or cutting-edge patterns
- Complex multi-system integration
- Regulatory/compliance requirements need latest information

### Expected Costs

- **Local models**: Free (0 cost)
- **Cloud usage**: ~$5-20/month if used 10% of the time
- **Total**: <$20/month vs $100+/month for cloud-only

## 🔧 Configuration Details

### Model Selection

The config includes both local and cloud models. By default:
- Chat starts with first local model (Qwen3 30B)
- Tab autocomplete uses Qwen3 30B (can be adjusted)
- Cloud models available in dropdown

### Switching Models

1. Open Continue chat
2. Click model name in the top bar
3. Select different model from dropdown
4. Continue with your question

### Custom Commands

All custom commands default to local models except `cloud-architect`. This keeps costs low while maintaining power when needed.

### MCP Integration

The Docker MCP gateway connects Continue.dev to additional capabilities through Model Context Protocol (MCP) servers. These are automatically available when Docker Desktop is running.

**Available MCP Servers:**

- **Brave Search** - Perform web searches directly from Continue chat
  - Search for documentation, examples, solutions
  - Get current information not in your codebase
  - Use: "Search for Python async best practices"

- **Context7** - Look up library and framework documentation
  - Automatically fetch documentation for your tech stack
  - Get detailed API references
  - Use: "Get docs for Terraform AWS provider"

- **Fetch** - Retrieve and parse web content
  - Download and analyze web pages
  - Extract content from URLs
  - Use: "Fetch and summarize this documentation URL"

- **Memory** - Persistent knowledge graph
  - Save important information for future reference
  - Build a persistent knowledge base
  - Use: "Remember this architecture decision"

- **Sequential Thinking** - Advanced reasoning for complex problems
  - Break down complex problems step-by-step
  - Deep reasoning and analysis
  - Use: Automatically triggered for complex tasks

**Enabling MCP Tools:**

In Continue.dev settings, you can auto-allow MCP tools for better UX. Go to Settings → Auto-allow MCP tools, and enable "Sequential Thinking" and "Memory" for automatic access.

## 🐛 Troubleshooting

### LM Studio Server Not Running

**Symptoms**: "Connection refused" errors in Continue

**Solution**:
1. Open LM Studio
2. Go to "Local Server" tab
3. Click "Start Server"
4. Load a model
5. Verify it's running on `http://localhost:1234/v1`

### Models Not Showing in Continue

**Solution**:
1. Check LM Studio model names match config exactly (use exact model IDs from config)
2. Ensure LM Studio server is running on port 1234
3. Verify the API endpoint includes `/v1`: `http://localhost:1234/v1`
4. Try restarting VSCode

### "Unexpected endpoint or method" Error

**Solution**:
This happens when LM Studio API endpoint is incorrect. Make sure config uses:
```yaml
apiBase: http://localhost:1234/v1
```
Not `http://localhost:1234` (missing `/v1`)

### Cloud Models Not Working

**Solution**:
1. Check API keys in `~/.continue/.env` are correct
2. Verify billing is set up in Anthropic/OpenAI dashboards
3. Check for rate limits in the dashboards
4. Restart VSCode after adding API keys

### Slow Performance with Local Models

**Solution**:
1. Use smaller models or stick with your primary (Qwen3 30B)
2. Close other apps to free RAM
3. Check Activity Monitor - models load into RAM when first used
4. Consider using one model consistently to avoid reload overhead

### Out of Memory Errors

**Solution**:
1. Use smaller models if 30B is too large
2. Unload other large applications
3. Consider upgrading RAM (but 36GB should handle 30B models fine)

### MCP Servers Not Working

**Solution**:
1. Ensure Docker Desktop is running
2. Check Docker MCP gateway is configured
3. Verify MCP tools are auto-allowed in Continue.dev settings
4. Restart VSCode after Docker starts

## 📊 Cost Monitoring

### Track Usage

Check these dashboards monthly:
- Anthropic: https://console.anthropic.com/settings/usage
- OpenAI: https://platform.openai.com/usage
- Voyage: https://www.voyageai.com/ (if using reranker)

### Optimize Costs

- Use local models for 90%+ of tasks
- Only switch to cloud for genuinely complex problems
- Set usage alerts in all dashboards
- Review monthly spending and adjust strategy
- Consider disconnecting cloud API keys if you never use them

## 🎉 You're Ready!

You now have a powerful, cost-optimized AI coding assistant:

- Fast responses from local models on your M4 MacBook
- Cloud AI available when you need extra capability
- MCP servers for enhanced capabilities
- Privacy for sensitive code (stays local by default)
- Low costs (~$10/month vs $100+/month cloud-only)
- Simple, clean interface in Continue.dev

Start by opening Continue chat and trying the `/cursor-agent` command!

## 📚 Additional Resources

- Continue.dev Documentation: https://docs.continue.dev
- Continue.dev Reference: https://docs.continue.dev/reference
- LM Studio Documentation: https://lmstudio.ai/docs
- Anthropic API Docs: https://docs.anthropic.com
- OpenAI API Docs: https://platform.openai.com/docs
- MCP Specification: https://modelcontextprotocol.io

## 📝 Configuration Summary

Your current setup includes:
- ✅ 4 local models (Qwen3 30B, Qwen2.5 32B, GPT-OSS 20B, DeepSeek 33B)
- ✅ 2 cloud models (Claude 3.5 Sonnet, GPT-4o)
- ✅ 1 reranker (Voyage)
- ✅ 7 context providers (diff, file, code, terminal, tree, open, currentFile)
- ✅ 3 custom commands (cursor-agent, cloud-architect, analyze-codebase)
- ✅ 1 MCP server (Docker MCP gateway)
- ✅ 1 documentation source (Continue docs)

For help, see `USAGE_TIPS.md` for best practices on interacting with the AI.

## 💡 Usage Examples

### Example 1: Quick Code Explanation

```
You: @currentFile Explain this code
AI: [Provides detailed explanation of the active file]
```

### Example 2: Multi-File Refactoring

```
You: /cursor-agent Refactor the authentication system to use JWT tokens
AI: [Asks clarifying questions]
You: Keep it simple, use existing patterns
AI: [Analyzes codebase, shows plan, executes refactoring]
```

### Example 3: Finding and Understanding Code

```
You: @code How is error handling implemented?
AI: [Searches codebase, shows examples]
You: @file:src/utils/errors.py Show me this specific implementation
AI: [Shows file contents and explanation]
```

### Example 4: Project Setup & Analysis

```
You: /init
AI: [Analyzes project, creates .continue/rules/CONTINUE.md with architecture]
You: /analyze-codebase ansible/roles/tanium_client
AI: [Reviews against CONTINUE.md, provides architectural analysis]
```

### Example 5: Documentation & Setup

```
You: /find-docs
AI: [Analyzes tech stack]
AI: Found: Terraform, Ansible, Home Assistant, Python
AI: [Fetches and ingests documentation]
You: Now explain how to add a new Ansible role
AI: [Uses ingested docs to provide accurate instructions]
```

### Example 6: Complex Architecture Decision

```
You: /cloud-architect Design a multi-region deployment strategy
AI: [Uses Claude/GPT-4 for sophisticated architectural guidance]
```

### Example 7: Debugging

```
You: The application is slow. @terminal Check the logs
AI: [Reviews terminal output]
AI: Found performance issue in database queries...
You: @code:database Fix the query optimization
AI: [Provides optimized query code]
```

## 📊 Expected Performance & Costs

### Local Models (Free)

- **Speed**: 15-30 tokens/second on M4 with Qwen 30B
- **First Response**: 2-5 seconds (includes model loading)
- **Subsequent Responses**: 1-3 seconds
- **RAM Usage**: 20-25GB for 30B models
- **Privacy**: 100% local, no data leaves your machine
- **Cost**: $0

### Cloud Models (Paid)

- **Speed**: 30-60 tokens/second
- **First Response**: 1-2 seconds
- **Cost**: ~$0.10-0.30 per 1K tokens
- **Usage**: Use for 10% of tasks = ~$5-20/month
- **Privacy**: Data sent to cloud providers

### Cost Optimization Tips

1. **Always start with local models** - They handle 90% of tasks excellently
2. **Try 2-3 different local models** before switching to cloud
3. **Use context providers efficiently** - Don't over-reference files
4. **Batch similar questions** - Group related tasks together
5. **Review cloud usage monthly** - Check dashboards to optimize

## 🎓 Learning Resources

- **Continue.dev Docs**: https://docs.continue.dev
- **Continue.dev Reference**: https://docs.continue.dev/reference
- **LM Studio Guide**: https://lmstudio.ai/docs
- **MCP Specification**: https://modelcontextprotocol.io
- **Anthropic Claude Docs**: https://docs.anthropic.com
- **OpenAI API Docs**: https://platform.openai.com/docs

## 🤝 Getting Help

- **Configuration Issues**: Check troubleshooting section above
- **Usage Questions**: See `USAGE_TIPS.md` for best practices
- **Feature Requests**: Continue.dev GitHub issues
- **Community**: Continue.dev Discord or forums
