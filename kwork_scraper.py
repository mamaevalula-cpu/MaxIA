import json
def save_data(data: dict) -> None:
    '''Сохраняет собранные данные о заказах в файл JSON'''
    file_path = 'data/freelance_applications.json'
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4, ensure_ascii=False)