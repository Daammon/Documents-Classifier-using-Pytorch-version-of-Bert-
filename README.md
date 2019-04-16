# Documents-Classifier-using-Pytorch-version-of-Bert-
Classifier of books and documents downloaded from manybooks doing web scraping. I used Pytorch version of Bert.
The algorithm used id Bert based on https://github.com/huggingface/pytorch-pretrained-BERT. You need to download or fork it
to use it with the files included in this repository.

There are 5 files: 

Data extraction:
Scraping of the web manybooks.net

Data processing:
Processing of the books and resize of them to have between 1-50 pages.Creation of 3 dataframes: train, dev and test set. The
test is different, it has only a few paragraphs per book as I wanted to test the accuracy varying the number of paragraphs
tested.

Books_Bert:
It is the language model finetuning

Books_Bert_Clasif:
The clasifier training and test.

Books_Bert_Clasif_Avg_Predict
It is the prediction using the test set. The number of paragraphs tested vary depending on the length of the document.

63% of accuracy testing only 1 paragraph is achieved and 71% testing several paragraphs and doing the average. It is important
to take into account than only a few pages per book are tested. In some books, only 1 or 2 paragraphs are tested and the 
books may have 400 pages. Additionally, there are books that are listed in two categories and others that are in a different
language.
