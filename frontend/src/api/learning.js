import request from '@/utils/request'

export const getLearningMaterialsAPI = ({ category = '', page = 1, size = 10 } = {}) =>
  request.get('/learning-materials', {
    params: {
      category: category || undefined,
      page,
      size,
    },
  })

export const getLearningMaterialDetailAPI = (id) => request.get(`/learning-materials/${id}`)

// PubMed 文献检索（医生学习板块独立调用，与 AI 问答解耦）
export const searchPubMedAPI = (query, maxResults = 5) =>
  request.post('/pubmed/search', { query, maxResults })
