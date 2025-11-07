#!/bin/bash

# A self-contained script to test the render.py tool (Version 2).
# It tests the new file:// protocol handling alongside all original features.

set -e # Exit immediately if a command exits with a non-zero status.

# --- Test Setup ---
TEST_DIR="/tmp/render_test_v2_$$" # Use process ID to create a unique test directory
RENDER_SCRIPT_PATH="$(pwd)/render.py" # Assumes render.py is in the current directory

# Check if render.py exists
if [ ! -f "$RENDER_SCRIPT_PATH" ]; then
    echo "Error: render.py not found in the current directory ($(pwd))."
    echo "Please run this script from the same directory as render.py."
    exit 1
fi

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test assertion helper
assert_contains() {
    local content="$1"
    local expected_substring="$2"
    local test_name="$3"
    # Use a delimiter for grep that is unlikely to be in the content
    if echo "$content" | grep -qF -- "$expected_substring"; then
        echo -e "${GREEN}✔ PASS:${NC} $test_name"
    else
        echo -e "${RED}✖ FAIL:${NC} $test_name"
        echo -e "  ${YELLOW}Expected to find:${NC} '$expected_substring'"
        echo -e "  ${YELLOW}Got:${NC} '$content'"
        exit 1
    fi
}

# --- Environment Creation ---
echo "--- Setting up test environment in $TEST_DIR ---"
mkdir -p "$TEST_DIR"
cp "$RENDER_SCRIPT_PATH" "$TEST_DIR/render.py"
cd "$TEST_DIR"

# 1. Create Project Structure
mkdir -p configs templates/KOS outputs

# 2. Create sample files
echo "repo_root: '$(pwd)/'" > config.yaml
echo "author: 'Project Author'" >> config.yaml

cat <<EOF > configs/KOS-main.yaml
- version: '1.0'
- project_name: 'Knowledge OS'
# Test both with and without leading slash for '@'
- template_file_with_slash: '@/templates/KOS/nested_template.md'
- template_file_no_slash: '@templates/KOS/nested_template.md'
EOF

cat <<EOF > configs/SYS-info.yaml
- user: 'system_user'
- current_date: '!date +"%Y-%m-%d"'
EOF

# Create an external file for absolute path testing
EXTERNAL_FILE_PATH="$TEST_DIR/external_absolute_file.txt"
echo "Content from absolute path file." > "$EXTERNAL_FILE_PATH"

# Create a file in the current working dir for relative file:// testing
echo "Content from relative path file." > "external_relative_file.txt"

cat <<EOF > templates/global.md
Author: {{ author }}
KOS Version: {{ KOS.version }}
System User: {{ SYS.user }}
EOF

cat <<EOF > templates/KOS/tool.md
# Welcome to {{ project_name }}
Version: {{ version }}
Author from global: {{ author }}
Today's Date: {{ SYS.current_date }}
EOF

cat <<EOF > templates/KOS/nested_template.md
This is a nested template file.
EOF

# --- Running Tests ---
echo -e "\n--- Starting Tests ---"

# Test 1: Standard Directory Rendering (Unchanged)
echo -e "\n${YELLOW}Test 1: Standard Directory Rendering${NC}"
python render.py > /dev/null
assert_contains "$(cat outputs/global.md)" "Author: Project Author" "Global template renders author"
assert_contains "$(cat outputs/global.md)" "KOS Version: 1.0" "Global template renders KOS version"
assert_contains "$(cat outputs/KOS/tool.md)" "# Welcome to Knowledge OS" "KOS template renders project name (scoped)"
assert_contains "$(cat outputs/KOS/tool.md)" "Author from global: Project Author" "KOS template renders global var"
assert_contains "$(cat outputs/KOS/tool.md)" "Today's Date: $(date +'%Y-%m-%d')" "Command execution for date works"

# Test 2: '@' Path Rendering (Corrected and Expanded)
echo -e "\n${YELLOW}Test 2: '@' Path Rendering (Relative to repo_root)${NC}"
result_slash=$(echo '{{ KOS.template_file_with_slash }}' | python render.py)
assert_contains "$result_slash" "This is a nested template file." "Renders content from '@/' path"
result_no_slash=$(echo '{{ KOS.template_file_no_slash }}' | python render.py)
assert_contains "$result_no_slash" "This is a nested template file." "Renders content from '@' path (no slash)"

# Test 3 & 4: Single Template and Stdin Rendering (Unchanged)
echo -e "\n${YELLOW}Test 3 & 4: Single Template & Stdin Rendering${NC}"
result=$(python render.py -t templates/global.md)
assert_contains "$result" "Author: Project Author" "'-t' renders correct content to stdout"
result=$(echo "Hello, {{ KOS.project_name }}!" | python render.py)
assert_contains "$result" "Hello, Knowledge OS!" "Stdin renders correctly"

# Test 5 & 6: Overrides and Scoping (Unchanged)
echo -e "\n${YELLOW}Test 5 & 6: Overrides and Scoping${NC}"
result=$(echo "{{ author }} / {{ KOS.version }}" | python render.py --set author="CLI User" --set KOS.version=2.0)
assert_contains "$result" "CLI User / 2.0" "'--set' overrides project config"
result=$(echo "Project: {{ project_name }}" | python render.py -s KOS)
assert_contains "$result" "Project: Knowledge OS" "'-s KOS' provides scope to stdin"


# Test 7: '--no-project-config' to isolate context
echo -e "\n${YELLOW}Test 7: Isolated context with '--no-project-config'${NC}"
# 创建一个符合 'PREFIX-description.yaml' 格式的文件
echo "- ext_var: 'External Value'" > external-testdata.yaml
# 在模板中使用前缀 'external'，并向 -c 传递正确的文件名
result=$(echo "{{ external.ext_var }} {{ author }}" | python render.py --no-project-config -c external-testdata.yaml)
assert_contains "$result" "External Value" "'--no-project-config' loads only '-c' file"
if echo "$result" | grep -qF "Project Author"; then
    echo -e "${RED}✖ FAIL:${NC} '--no-project-config' should not load project author"
    exit 1
else
    echo -e "${GREEN}✔ PASS:${NC} '--no-project-config' does not load project config"
fi

# Test 8 & 9: Config and Repo Root Overrides (Unchanged)
echo -e "\n${YELLOW}Test 8 & 9: Config and Repo Root Overrides${NC}"
echo "author: 'Global Override Author'" > external_global.yaml
result=$(echo "{{ author }}" | python render.py -g external_global.yaml)
assert_contains "$result" "Global Override Author" "'-g' overrides base global config"
mkdir -p other_root/templates
echo "other root file" > other_root/templates/file.md
result=$(echo "{{ KOS.other_file }}" | python render.py -r "$(pwd)/other_root/" --set 'KOS.other_file=@templates/file.md')
assert_contains "$result" "other root file" "'-r' correctly sets repo_root for '@' paths"

# Test 10: Quiet mode '-q' (Unchanged)
echo -e "\n${YELLOW}Test 10: Quiet mode '-q'${NC}"
output_verbose=$(python render.py -t templates/global.md 2>&1)
output_quiet=$(python render.py -q -t templates/global.md 2>&1)
lines_verbose=$(echo "$output_verbose" | wc -l)
lines_quiet=$(echo "$output_quiet" | wc -l)
if [ "$lines_quiet" -lt "$lines_verbose" ]; then
    echo -e "${GREEN}✔ PASS:${NC} Quiet mode reduces output verbosity"
else
    echo -e "${RED}✖ FAIL:${NC} Quiet mode did not reduce output"
    echo "Verbose lines: $lines_verbose, Quiet lines: $lines_quiet"
    exit 1
fi

# --- NEW TESTS for file:// protocol ---

# Test 11: file:// with absolute path
echo -e "\n${YELLOW}Test 11: 'file://' with absolute path${NC}"
result=$(echo "{{ external.file }}" | python render.py --no-project-config --set "external.file=file://${EXTERNAL_FILE_PATH}")
assert_contains "$result" "Content from absolute path file." "'file://' renders absolute path correctly"

# Test 12: file:// with relative path (to current working directory)
echo -e "\n${YELLOW}Test 12: 'file://' with relative path${NC}"
result=$(echo "{{ external.file }}" | python render.py --no-project-config --set "external.file=file://external_relative_file.txt")
assert_contains "$result" "Content from relative path file." "'file://' renders relative path correctly"


# --- Cleanup ---
echo -e "\n--- All tests passed! Cleaning up. ---"
cd ..
rm -rf "$TEST_DIR"

echo -e "${GREEN}✨ Test script finished successfully.${NC}"
