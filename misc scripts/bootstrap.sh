#!/bin/bash
# =============================================================================
# System Terminal/Shell Bootstrap Script
# =============================================================================
# This script recreates your terminal/shell setup from scratch after a system wipe
# It installs and configures zsh, oh-my-zsh, starship, and other shell tools

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Bootstrapping terminal/shell environment from scratch...${NC}"

# =============================================================================
# PACKAGE MANAGER SETUP
# =============================================================================

echo -e "${YELLOW}📦 Setting up package manager...${NC}"

# Detect OS and install package manager
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS - install Homebrew if not present
    OS_TYPE="macos"
    if ! command -v brew >/dev/null 2>&1; then
        echo -e "${YELLOW}Installing Homebrew...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Add Homebrew to PATH for Apple Silicon Macs
        if [[ $(uname -m) == "arm64" ]]; then
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    else
        echo -e "${GREEN}✅ Homebrew already installed${NC}"
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux - detect specific distribution
    if [ -f /etc/os-release ]; then
        source /etc/os-release
        case "$ID" in
            ubuntu|debian|pop|elementary|linuxmint)
                OS_TYPE="ubuntu"
                echo -e "${GREEN}✅ Detected Ubuntu/Debian-based distribution: $PRETTY_NAME${NC}"
                ;;
            centos|rhel|fedora|rocky|almalinux)
                OS_TYPE="centos"
                echo -e "${GREEN}✅ Detected CentOS/RHEL-based distribution: $PRETTY_NAME${NC}"
                ;;
            arch|manjaro)
                OS_TYPE="arch"
                echo -e "${GREEN}✅ Detected Arch-based distribution: $PRETTY_NAME${NC}"
                ;;
            *)
                echo -e "${YELLOW}⚠️  Unrecognized distribution: $PRETTY_NAME${NC}"
                echo -e "${YELLOW}Trying to detect package manager...${NC}"
                # Fallback to package manager detection
                if command -v apt >/dev/null 2>&1; then
                    OS_TYPE="ubuntu"
                    echo -e "${GREEN}✅ Using apt package manager${NC}"
                elif command -v yum >/dev/null 2>&1 || command -v dnf >/dev/null 2>&1; then
                    OS_TYPE="centos"
                    echo -e "${GREEN}✅ Using yum/dnf package manager${NC}"
                elif command -v pacman >/dev/null 2>&1; then
                    OS_TYPE="arch"
                    echo -e "${GREEN}✅ Using pacman package manager${NC}"
                else
                    echo -e "${RED}❌ Unsupported Linux distribution${NC}"
                    exit 1
                fi
                ;;
        esac
    else
        echo -e "${RED}❌ Cannot detect Linux distribution${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ Unsupported operating system: $OSTYPE${NC}"
    exit 1
fi

# =============================================================================
# ESSENTIAL TOOLS INSTALLATION
# =============================================================================

echo -e "${YELLOW}🛠️  Installing essential tools...${NC}"

# Function to install packages based on OS
install_package() {
    local package="$1"
    
    # Map package names to distribution-specific names
    case "$OS_TYPE" in
        "macos")
            brew install "$package"
            ;;
        "ubuntu")
            case "$package" in
                "tree") package="tree" ;;
                "htop") package="htop" ;;
                "jq") package="jq" ;;
                "fzf") package="fzf" ;;
                "direnv") package="direnv" ;;
                "vim") package="vim" ;;
                "curl") package="curl" ;;
                "wget") package="wget" ;;
                "git") package="git" ;;
                "zsh") package="zsh" ;;
            esac
            apt update && apt install -y "$package"
            ;;
        "centos")
            case "$package" in
                "tree") package="tree" ;;
                "htop") package="htop" ;;
                "jq") package="jq" ;;
                "fzf") package="fzf" ;;
                "direnv") package="direnv" ;;
                "vim") package="vim" ;;
                "curl") 
                    # Handle curl-minimal conflict on RHEL-based systems
                    if rpm -q curl-minimal >/dev/null 2>&1; then
                        package="curl --allowerasing"
                    else
                        package="curl"
                    fi
                    ;;
                "wget") package="wget" ;;
                "git") package="git" ;;
                "zsh") package="zsh" ;;
            esac
            # Try dnf first (Fedora/newer RHEL), then yum
            if command -v dnf >/dev/null 2>&1; then
                dnf install -y $package
            else
                yum install -y $package
            fi
            ;;
        "arch")
            case "$package" in
                "tree") package="tree" ;;
                "htop") package="htop" ;;
                "jq") package="jq" ;;
                "fzf") package="fzf" ;;
                "direnv") package="direnv" ;;
                "vim") package="vim" ;;
                "curl") package="curl" ;;
                "wget") package="wget" ;;
                "git") package="git" ;;
                "zsh") package="zsh" ;;
            esac
            # Initialize pacman database if needed and install package
            pacman -Sy --noconfirm "$package"
            ;;
    esac
}

# Install essential tools
ESSENTIAL_TOOLS=("zsh" "git" "curl" "wget" "vim" "tree")

for tool in "${ESSENTIAL_TOOLS[@]}"; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo -e "${YELLOW}Installing $tool...${NC}"
        install_package "$tool"
    else
        echo -e "${GREEN}✅ $tool already installed${NC}"
    fi
done

# Install chsh command for RHEL-based systems
if ! command -v chsh >/dev/null 2>&1 && [[ "$OS_TYPE" == "centos" ]]; then
    echo -e "${YELLOW}Installing chsh command...${NC}"
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y util-linux-user
    else
        yum install -y util-linux
    fi
fi

# =============================================================================
# ZSH SETUP
# =============================================================================

echo -e "${YELLOW}🐚 Setting up zsh as default shell...${NC}"

# Install Oh My Zsh
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    echo -e "${YELLOW}Installing Oh My Zsh...${NC}"
    sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
else
    echo -e "${GREEN}✅ Oh My Zsh already installed${NC}"
fi

# Set zsh as default shell
ZSH_PATH=""
case "$OS_TYPE" in
    "macos")
        ZSH_PATH="/bin/zsh"
        ;;
    "ubuntu"|"centos"|"arch")
        ZSH_PATH="/usr/bin/zsh"
        ;;
esac

if [ "$SHELL" != "$ZSH_PATH" ]; then
    echo -e "${YELLOW}Setting zsh as default shell...${NC}"
    if [[ "$OS_TYPE" == "macos" ]]; then
        chsh -s "$ZSH_PATH"
    else
        # Linux - handle both root and non-root users
        if [ "$(id -u)" -eq 0 ]; then
            # Running as root
            chsh -s "$ZSH_PATH"
        else
            # Running as regular user
            CURRENT_USER="${USER:-$(whoami)}"
            if command -v sudo >/dev/null 2>&1 && sudo chsh -s "$ZSH_PATH" "$CURRENT_USER" 2>/dev/null; then
                echo -e "${GREEN}✅ Set zsh as default shell${NC}"
            else
                echo -e "${YELLOW}⚠️  Could not change shell automatically. Please run:${NC}"
                echo -e "${YELLOW}   sudo chsh -s $ZSH_PATH $CURRENT_USER${NC}"
            fi
        fi
    fi
else
    echo -e "${GREEN}✅ zsh is already default shell${NC}"
fi

# =============================================================================
# STARSHIP PROMPT INSTALLATION
# =============================================================================

echo -e "${YELLOW}⭐ Installing and configuring Starship prompt...${NC}"

# Install Starship
if ! command -v starship >/dev/null 2>&1; then
    echo -e "${YELLOW}Installing Starship...${NC}"
    curl -sS https://starship.rs/install.sh | sh -s -- --yes
else
    echo -e "${GREEN}✅ Starship already installed${NC}"
fi

# Create starship config directory
mkdir -p "$HOME/.config"

# Create your exact starship configuration
echo -e "${YELLOW}Creating starship configuration...${NC}"
cat > "$HOME/.config/starship.toml" << 'EOF'
format = """\
[ ](bg:#030B16 fg:#7DF9AA)\
[ ](bg:#7DF9AA fg:#090c0c)\
[ ](fg:#7DF9AA bg:#1C3A5E)\
$time\
[ ](fg:#1C3A5E bg:#3B76F0)\
$directory\
[ ](fg:#3B76F0 bg:#FCF392)\
$git_branch\
$git_status\
$git_metrics\
[ ](fg:#FCF392 bg:#030B16)\
$character\
"""

[directory]
format = "[  $path ]($style)"
style = "fg:#E4E4E4 bg:#3B76F0"

[git_branch]
format = '[ $symbol$branch(:$remote_branch) ]($style)'
symbol = "   "
style = "fg:#1C3A5E bg:#FCF392"

[git_status]
format = '[$all_status]($style)'
style = "fg:#1C3A5E bg:#FCF392"

[git_metrics]
format = "([+$added]($added_style))[]($added_style)"
added_style = "fg:#1C3A5E bg:#FCF392"
deleted_style = "fg:bright-red bg:235"
disabled = false

[hg_branch]
format = "[ $symbol$branch ]($style)"
symbol = " "

[cmd_duration]
format = "[  $duration ]($style)"
style = "fg:bright-white bg:18"

[character]
success_symbol = '[ ➜](bold green) '
error_symbol = '[ ✗](#E84D44) '

[time]
disabled = false
time_format = "%R" # Hour:Minute Format
style = "bg:#1d2230"
format = '[[  $time ](bg:#1C3A5E fg:#8DFBD2)]($style)'
EOF

echo -e "${GREEN}✅ Created starship configuration${NC}"

# =============================================================================
# ZSH CONFIGURATION
# =============================================================================

echo -e "${YELLOW}🐚 Setting up zsh configuration...${NC}"

# Create your exact .zshrc configuration
echo -e "${YELLOW}Creating .zshrc configuration...${NC}"
cat > "$HOME/.zshrc" << 'EOF'
# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:$HOME/.local/bin:/usr/local/bin:$PATH

# Path to your Oh My Zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time Oh My Zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME=""

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment one of the following lines to change the auto-update behavior
# zstyle ':omz:update' mode disabled  # disable automatic updates
# zstyle ':omz:update' mode auto      # update automatically without asking
# zstyle ':omz:update' mode reminder  # just remind me to update when it's time

# Uncomment the following line to change how often to auto-update (in days).
# zstyle ':omz:update' frequency 13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS="true"

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# You can also set it to another string to have that shown instead of the default red dots.
# e.g. COMPLETION_WAITING_DOTS="%F{yellow}waiting...%f"
# Caution: this setting can cause issues with multiline prompts in zsh < 5.7.1 (see #5765)
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(git)

source $ZSH/oh-my-zsh.sh

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='nvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch $(uname -m)"

# Set personal aliases, overriding those provided by Oh My Zsh libs,
# plugins, and themes. Aliases can be placed here, though Oh My Zsh
# users are encouraged to define aliases within a top-level file in
# the $ZSH_CUSTOM folder, with .zsh extension. Examples:
# - $ZSH_CUSTOM/aliases.zsh
# - $ZSH_CUSTOM/macos.zsh
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"
eval "$(starship init zsh)"

# Add Homebrew OpenSSH tools to PATH (macOS only)
if [[ "\$OSTYPE" == "darwin"* ]]; then
    export PATH="/opt/homebrew/opt/openssh/bin:\$PATH"
fi

# Added by LM Studio CLI (lms) - only if directory exists
if [ -d "\$HOME/.lmstudio/bin" ]; then
    export PATH="\$PATH:\$HOME/.lmstudio/bin"
fi
# End of LM Studio CLI section

. "\$HOME/.local/bin/env"

# The following lines have been added by Docker Desktop to enable Docker CLI completions.
# Only add if Docker completions directory exists
if [ -d "\$HOME/.docker/completions" ]; then
    fpath=(\$HOME/.docker/completions \$fpath)
    autoload -Uz compinit
    compinit
    # End of Docker CLI completions
    FPATH="\$HOME/.docker/completions:\$FPATH"
    autoload -Uz compinit
    compinit
fi
EOF

echo -e "${GREEN}✅ Created .zshrc configuration${NC}"

# Create .zprofile
echo -e "${YELLOW}Creating .zprofile...${NC}"
cat > "$HOME/.zprofile" << 'EOF'

# Initialize Homebrew (macOS only)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ $(uname -m) == "arm64" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ $(uname -m) == "x86_64" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi
EOF

echo -e "${GREEN}✅ Created .zprofile${NC}"

# Create .local/bin/env
echo -e "${YELLOW}Creating ~/.local/bin/env...${NC}"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/env" << 'EOF'
#!/bin/sh
# add binaries to PATH if they aren't added yet
# affix colons on either side of $PATH to simplify matching
case ":${PATH}:" in
    *:"$HOME/.local/bin":*)
        ;;
    *)
        # Prepending path in case a system-installed binary needs to be overridden
        export PATH="$HOME/.local/bin:$PATH"
        ;;
esac
EOF
chmod +x "$HOME/.local/bin/env"

echo -e "${GREEN}✅ Created ~/.local/bin/env${NC}"

# =============================================================================
# ADDITIONAL TOOLS (Optional)
# =============================================================================

echo -e "${YELLOW}🛠️  Installing additional useful tools...${NC}"

# Install additional tools that might be useful
ADDITIONAL_TOOLS=("direnv" "tree" "htop" "jq" "fzf")

for tool in "${ADDITIONAL_TOOLS[@]}"; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo -e "${YELLOW}Installing $tool...${NC}"
        if install_package "$tool" 2>/dev/null; then
            echo -e "${GREEN}✅ $tool installed successfully${NC}"
        else
            echo -e "${YELLOW}⚠️  $tool not available in this distribution's repositories${NC}"
        fi
    else
        echo -e "${GREEN}✅ $tool already installed${NC}"
    fi
done

# =============================================================================
# FINAL SETUP
# =============================================================================

echo -e "${YELLOW}🔧 Final setup...${NC}"

# Create ~/.local/bin directory if it doesn't exist
mkdir -p "$HOME/.local/bin"

# Set up direnv if installed
if command -v direnv >/dev/null 2>&1; then
    echo -e "${YELLOW}Setting up direnv hook...${NC}"
    # Add direnv hook to .zshrc if not already present
    if ! grep -q "direnv hook zsh" "$HOME/.zshrc"; then
        echo 'eval "$(direnv hook zsh)"' >> "$HOME/.zshrc"
        echo -e "${GREEN}✅ Added direnv hook to .zshrc${NC}"
    else
        echo -e "${GREEN}✅ direnv hook already configured${NC}"
    fi
fi

# Set proper permissions
chmod +x "$HOME/.local/bin/env"

echo -e "${GREEN}🎉 System bootstrap complete!${NC}"
echo ""
echo -e "${BLUE}What was installed/configured:${NC}"
echo "  ✅ Package manager (Homebrew on macOS)"
echo "  ✅ Essential tools (zsh, git, curl, wget, vim, tree)"
echo "  ✅ Oh My Zsh framework"
echo "  ✅ Starship prompt with your custom configuration"
echo "  ✅ Complete .zshrc setup matching your current config"
echo "  ✅ .zprofile and ~/.local/bin/env"
echo "  ✅ Additional tools (direnv, htop, jq, fzf)"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "1. Restart your terminal or run: source ~/.zshrc"
echo "2. Your shell should now look and behave exactly like before"
echo "3. All your custom configurations have been restored"
echo ""
echo -e "${GREEN}Your terminal setup has been restored! 🎉${NC}"
