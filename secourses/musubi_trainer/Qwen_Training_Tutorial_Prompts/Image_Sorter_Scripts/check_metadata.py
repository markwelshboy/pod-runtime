import os
from PIL import Image
import json

# Get a sample file
files = os.listdir('local')
sample_file = os.path.join('local', files[0])
print('Sample filename:', sample_file)

# Try to read EXIF data
try:
    img = Image.open(sample_file)
    exif_data = img._getexif()
    if exif_data:
        print('EXIF data found')
        for tag, value in exif_data.items():
            print(f'{tag}: {value}')
    else:
        print('No EXIF data found')
except Exception as e:
    print(f'Error reading EXIF: {e}')

# Try to read PNG metadata
try:
    img = Image.open(sample_file)
    metadata = img.info
    print('PNG metadata:')
    for key, value in metadata.items():
        print(f'{key}: {value}')
        if key == 'parameters' or key == 'prompt':
            print('Found prompt in metadata!')
except Exception as e:
    print(f'Error reading PNG metadata: {e}')

# Check the filename structure
print('\nFilename analysis:')
print('Full filename:', sample_file)
# Remove the common prefix and suffix
filename = os.path.basename(sample_file)
if filename.startswith('0007001-'):
    prompt_part = filename[9:]  # Remove '0007001-'
    if '-My_Qwen_Edit_Fine_Tuned_Model_Without_Co' in prompt_part:
        prompt = prompt_part.split('-My_Qwen_Edit_Fine_Tuned_Model_Without_Co')[0]
        print('Extracted prompt:', prompt)
