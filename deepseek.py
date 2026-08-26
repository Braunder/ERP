import os
import argparse
import logging

def is_binary(file_path):
    """Проверяет, является ли файл бинарным."""
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            if b'\0' in chunk:
                return True
    except Exception as e:
        return True
    return False

def should_ignore(path, ignore_dirs, ignore_exts):
    """Определяет, нужно ли игнорировать файл/директорию."""
    
    if os.path.basename(path) in ignore_dirs:
        return True
    if any(path.startswith(prefix) for prefix in ignore_dirs):
        return True
    if os.path.isfile(path):
        ext = os.path.splitext(path)[1]
        if ext in ignore_exts:
            return True
    return False

def collect_files(root_dir, output_file, ignore_dirs, ignore_exts):
    """Собирает содержимое файлов в выходной файл."""
    
    processed_files = 0
    ignored_files = 0
    error_files = 0
    
    with open(output_file, 'w', encoding='utf-8') as out_f:
        for root, dirs, files in os.walk(root_dir):
            # Удаляем игнорируемые директории из списка для обхода
            original_dirs = len(dirs)
            dirs[:] = [d for d in dirs if not should_ignore(os.path.join(root, d), ignore_dirs, ignore_exts)]
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_dir)
                
                if should_ignore(file_path, ignore_dirs, ignore_exts):
                    ignored_files += 1
                    continue
                
                if is_binary(file_path):
                    ignored_files += 1
                    continue
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as in_f:
                        contents = in_f.read()
                except UnicodeDecodeError:
                    try:
                        with open(file_path, 'r', encoding='latin-1') as in_f:
                            contents = in_f.read()
                    except Exception as e:
                        error_files += 1
                        continue
                except Exception as e:
                    error_files += 1
                    continue
                
                out_f.write(f"# {rel_path}\n")
                out_f.write(contents)
                out_f.write("\n\n")
                processed_files += 1
    

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description='Сборка кода проекта в один файл')
    parser.add_argument('-d', '--dir', default='.', help='Корневая директория проекта')
    parser.add_argument('-o', '--output', default='project_code.txt', help='Выходной файл')
    args = parser.parse_args()

    # Игнорируемые элементы
    IGNORE_DIRS = {
        '.git', '__pycache__', 'node_modules', '.venv', 
        '.vscode', '.idea', 'dist', 'build', 'target',
        'models', 'venv', 'cache', 'lib', 'llama.cpp', 
        'whisper.cpp', 'deepseek.py', 'prompts', 'templates',
        'py_venv', '.blip-image-captioning-large', 'TODO',
        '.tests', 'dataset', 'llama.cpp', 'rvc_python'
        
    }
    IGNORE_EXTS = {
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', 
        '.pdf', '.zip', '.tar', '.gz', '.exe', '.dll', 
        '.bin', '.db', '.pyc', '.class', '.jar', '.names',
        '.onnx', '.pt', '.log', '.txt', '.json', '.env',
        '.jsonl', '.gitignore'
    }


    try:
        collect_files(
            root_dir=args.dir,
            output_file=args.output,
            ignore_dirs=IGNORE_DIRS,
            ignore_exts=IGNORE_EXTS
        )
        print(f"Код проекта сохранен в: {args.output}")
    except Exception as e:
        print(f"Ошибка: {e}")
        exit(1)