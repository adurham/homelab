# Continue.dev Usage Tips

How to get the best results from your local + cloud AI setup.

## 🎯 Getting Started

### Basic Workflow

1. **Open Continue chat** (Cmd+L on Mac, Ctrl+L on Windows)
2. **Pick a model**:
   - Start with a local model (Qwen3 30B is great)
   - Switch to cloud models only when needed
3. **Ask your question** or use `@codebase` for context

### Custom Commands

Try these specialized commands:

- **`/init`** - Create `.continue/rules/CONTINUE.md` with project architecture (Continue's built-in command)
- **`/cursor-agent`** - Full autonomous agent for any task
- **`/cloud-architect`** - Complex architectural problems (uses paid models)
- **`/analyze-codebase`** - Analyze components against CONTINUE.md architecture
- **`/find-docs`** - Find and ingest documentation for your tech stack

## 💡 Best Practices

### Using Context Providers

Reference files and code with these:
- **`@code`** - Search across your codebase
- **`@file`** - Reference specific files
- **`@tree`** - Show directory structure
- **`@currentFile`** - Get context from your active file
- **`@open`** - Reference multiple open files
- **`@diff`** - See what changed
- **`@terminal`** - Terminal output

**Example**: "Explain this code: `@file:src/main.py`"

### Cost Optimization

**Use Local Models For** (Free):
- Code generation and editing
- Debugging and explanations
- Refactoring and cleanup
- Writing tests
- Documentation

**Use Cloud Models For** (Paid):
- Complex architecture decisions
- Novel algorithms
- Security audits
- When local models give poor results

**Tip**: Try 2-3 different local models before switching to cloud.

### Getting Better Answers

**Be Specific**:
- ❌ "Fix this code"
- ✅ "Add error handling to the API call in fetchData()"

**Provide Context**:
- Use `@code` or `@file` to include relevant code
- Mention what you've already tried
- Include error messages

**Ask Follow-ups**:
- "Can you explain why?"
- "What are the trade-offs?"
- "Show me an alternative approach"

### Codebase Analysis

For analyzing code against architecture:

**Recommended workflow:**
1. **First time setup**: Run `/init` to create `.continue/rules/CONTINUE.md` (project architecture guide)
2. **Then analyze**: Use `/analyze-codebase` to check specific components against the architecture
3. **Iterate**: Run `/init` again when project structure changes significantly

**Example workflow**:
```
You: /init
AI: [Analyzes project, creates CONTINUE.md with architecture and guidelines]
You: /analyze-codebase ansible/roles/tanium_client
AI: [Reviews against CONTINUE.md, checks alignment with standards, suggests improvements]
You: @tree Tell me about the ansible/ directory structure
AI: [Explains structure with context from CONTINUE.md]
```

**Pro tip**: `/init` creates `.continue/rules/CONTINUE.md` which Continue automatically loads into context for all interactions!

### Finding Documentation

Use the **`/find-docs`** command to automatically:
1. Detect your tech stack
2. Find official documentation
3. Ingest documentation into memory
4. Make it searchable for future queries

Great for new projects or unfamiliar technologies!

## 🔧 Troubleshooting

### Local Models Not Responding

**Check**:
1. LM Studio server is running
2. A model is loaded
3. Endpoint is `http://localhost:1234/v1`

**Try**:
- Switch to a different local model
- Restart LM Studio
- Check system resources (RAM/CPU)

### Getting Wrong Answers

**Try**:
1. Switch to a different local model
2. Provide more context with `@file` or `@code`
3. Be more specific in your question
4. If still stuck, switch to cloud model

### Slow Performance

**Optimize**:
- Use smaller models (Qwen2.5 32B vs 30B)
- Close other applications
- Stick to one model (avoids reload overhead)
- Use lighter context providers

### Memory Issues

**If running out of RAM**:
- Use smaller models
- Close other applications
- Restart VSCode to clear memory
- Stick to 4-bit quantized models

## 🎓 Advanced Tips

### Model Switching Strategy

**For Coding Tasks**:
1. Start with Qwen3 30B (best for coding)
2. If too slow, try Qwen2.5 32B
3. For faster responses, use GPT-OSS 20B

**For Analysis**:
1. Start with DeepSeek Coder 33B (great analysis)
2. For complex problems, try cloud models

### Custom Prompts

Create your own custom prompts:
1. Use existing ones as templates
2. Specify the task clearly
3. Include context you want referenced
4. Add to `continue-config.yaml` under `prompts:`

### MCP Integration

Your setup includes MCP servers for enhanced capabilities:

- **Brave Search** - Find information online
- **Context7** - Library documentation
- **Fetch** - Get web content
- **Memory** - Persistent knowledge graph
- **Sequential Thinking** - Advanced reasoning

Use these automatically or explicitly request them.

### Context Provider Strategies

**For File Navigation**:
```
@tree Show me the terraform directory structure
```

**For Code Review**:
```
@code Review this: [paste code] and suggest improvements
```

**For Understanding Changes**:
```
@diff Explain what changed in this commit
```

**For Multi-File Context**:
```
@open How do these files relate to each other?
```

## 📊 Monitoring Usage

**Check Your Costs**:
- Anthropic: https://console.anthropic.com/settings/usage
- OpenAI: https://platform.openai.com/usage
- Voyage: https://www.voyageai.com/

**Optimize**:
- Review monthly spending
- Identify tasks that needed cloud
- Try local models first next time
- Set usage alerts in dashboards

## 🚀 Pro Tips

1. **Create a habit**: Start every task with local models
2. **Be patient**: Local models are fast but may need clearer instructions
3. **Iterate**: Refine your questions based on responses
4. **Document**: Save good prompts for reuse
5. **Experiment**: Try different models for different tasks

## 💬 Example Interactions

### Quick Code Fix
```
You: Fix the bug in @file:src/utils.py line 42
AI: [Provides fix with explanation]
```

### Complex Refactoring
```
You: /cursor-agent Refactor the authentication system to use JWT
AI: [Asks clarifying questions, provides plan, executes]
```

### Documentation Search
```
You: /find-docs
AI: [Analyzes stack, finds docs, ingests them]
You: Now explain how to use the Terraform provider
AI: [Provides answer using ingested docs]
```

### Multi-Step Task
```
You: @tree Show me the project structure
AI: [Shows tree]
You: @code How does ansible/roles/tanium_client work?
AI: [Explains Ansible role]
You: Can you suggest improvements?
AI: [Provides suggestions]
```

Happy coding with AI! 🎉
